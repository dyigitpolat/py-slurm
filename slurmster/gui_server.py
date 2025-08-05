from __future__ import annotations
from typing import Dict, Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState
from pathlib import Path

from .connection import SSHConnection
from .core import submit_all, cancel
from .registry import Registry
from .remote_utils import _resolve_remote_path, _run_state_from_markers, _squeue_state


# -----------------------------------------------------------------------------
# Helper utilities
# -----------------------------------------------------------------------------

def _open_conn(host: str, user: str, port: int, password: str | None = None, key_filename: str | None = None) -> SSHConnection:
    """Open a fresh SSH connection. Each request uses its own connection so we
    don't share Paramiko clients across threads (FastAPI's default concurrency
    model may run endpoints on different threads).
    """
    return (
        SSHConnection(host=host, user=user, port=port, password=password, key_filename=key_filename)
        .connect()
    )


def _list_jobs(conn: SSHConnection, cfg) -> list[Dict[str, Any]]:
    """Return a list of tracked runs augmented with their latest state.

    This re-implements parts of slurmster.run_status.status but returns a JSON
    serialisable structure instead of printing tables.
    """
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    reg = Registry(conn.user, conn.host, remote_dir, cfg.get("_local_root"))
    runs = reg.all_runs()

    result: list[Dict[str, Any]] = []

    def _parse_exp_name(exp: str) -> dict[str, str]:
        """Fallback parser for legacy registry entries without explicit params."""
        if not exp.startswith("exp_"):
            return {}
        parts = exp[4:].split("_")
        if len(parts) % 2 != 0:
            # cannot form key/value pairs reliably
            return {}
        return {parts[i]: parts[i + 1] for i in range(0, len(parts), 2)}

    for r in runs:
        job_id = r.get("job_id")
        run_dir = r.get("run_dir")

        # Determine live state
        state = _run_state_from_markers(conn, run_dir) if run_dir else "UNKNOWN"
        if state == "UNKNOWN" and job_id:
            sq = _squeue_state(conn, job_id)
            if sq == "COMPLETED":
                sq = "FINISHED"
            state = sq or state

        # ensure params present
        params = r.get("params") or _parse_exp_name(r.get("exp_name", ""))

        # persist back any updates
        if state and state != r.get("state"):
            reg.update_run(job_id=job_id, state=state)
        if params and not r.get("params"):
            reg.update_run(job_id=job_id, params=params)

        job_repr = dict(r)  # shallow copy
        job_repr["state"] = state
        job_repr["params"] = params
        result.append(job_repr)

    return result


# -----------------------------------------------------------------------------
# FastAPI application factory
# -----------------------------------------------------------------------------

def create_app(cfg, *, ssh_host: str, ssh_user: str, ssh_port: int = 22, password: str | None = None, key_filename: str | None = None) -> FastAPI:
    """Create the FastAPI application bound to a specific SSH host/user.

    The configuration is passed in-memory so the server does not parse YAML on
    each request.
    """

    app = FastAPI(title="Slurmster GUI", version="0.1")

    # ---------------------------------------------------------------------
    # REST endpoints
    # ---------------------------------------------------------------------

    @app.get("/api/jobs")
    def api_list_jobs():
        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            jobs = _list_jobs(conn, cfg)
            # sort by job id (numeric) descending so newest first
            jobs.sort(key=lambda j: int(j.get("job_id") or 0), reverse=True)
            return jobs
        finally:
            conn.close()

    @app.post("/api/jobs/submit")
    def api_submit_jobs():
        """Submit all jobs defined in the YAML config. Equivalent to the CLI
        `slurmster submit` command with `--no-monitor`.
        """
        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            submit_all(conn, cfg, user=ssh_user, host=ssh_host, monitor=False)
            return {"detail": "submitted"}
        finally:
            conn.close()

    @app.post("/api/jobs/submit_single")
    def api_submit_single(params: dict):
        """Submit a single job with the provided params dict (no grid)."""
        if not isinstance(params, dict):
            raise ValueError("JSON body must be object with params")
        from copy import deepcopy

        single_cfg = deepcopy(cfg)
        run_section = single_cfg.setdefault("run", {})
        run_section["experiments"] = [params]
        # Remove grid if present to avoid Cartesian expansion
        run_section.pop("grid", None)

        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            submit_all(conn, single_cfg, user=ssh_user, host=ssh_host, monitor=False)
            return {"detail": "submitted single"}
        finally:
            conn.close()

    @app.post("/api/jobs/{job_id}/cancel")
    def api_cancel_job(job_id: str):
        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            cancel(conn, cfg, job_id=job_id)
            return {"detail": f"cancelled {job_id}"}
        finally:
            conn.close()

    @app.post("/api/jobs/{job_id}/fetch")
    def api_fetch_job(job_id: str):
        """Fetch outputs for a finished job by job ID."""
        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            from .fetch import fetch
            fetch(conn, cfg, job_id=job_id)
            return {"detail": f"fetched job {job_id}"}
        finally:
            conn.close()

    @app.post("/api/jobs/fetch-all")
    def api_fetch_all_jobs():
        """Fetch outputs for all finished jobs."""
        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            from .fetch import fetch
            fetch(conn, cfg)  # No exp_name means fetch all
            return {"detail": "fetched all finished jobs"}
        finally:
            conn.close()

    @app.get("/api/jobs/{job_id}/browse")
    def api_browse_job_directory(job_id: str, path: str = ""):
        """Browse files in a job's run directory."""
        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            from .registry import Registry
            remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
            reg = Registry(ssh_user, ssh_host, remote_dir, cfg.get("_local_root"))
            run = reg.find_run(job_id=job_id)
            
            if not run:
                return {"error": f"No run found for job_id {job_id}"}
            
            run_dir = run.get("run_dir")
            if not run_dir:
                return {"error": f"No run directory found for job_id {job_id}"}
            
            # Construct full path
            browse_path = run_dir
            if path:
                # Ensure path doesn't escape the run directory
                import os.path
                browse_path = os.path.join(run_dir, path.lstrip('/'))
            
            # List directory contents
            try:
                exit_code, stdout, stderr = conn.bash(f"ls -la '{browse_path}' 2>/dev/null || echo 'ERROR_NOT_FOUND'")
                if "ERROR_NOT_FOUND" in stdout or exit_code != 0:
                    return {"error": f"Directory not found: {path}"}
                
                files = []
                lines = stdout.strip().split('\n')
                for line in lines[1:]:  # Skip the 'total' line
                    if not line.strip():
                        continue
                    
                    parts = line.split(None, 8)
                    if len(parts) < 9:
                        continue
                    
                    permissions = parts[0]
                    size = parts[4]
                    date_parts = parts[5:8]
                    name = parts[8]
                    
                    # Skip . and ..
                    if name in ['.', '..']:
                        continue
                    
                    is_directory = permissions.startswith('d')
                    
                    files.append({
                        "name": name,
                        "size": size,
                        "date": " ".join(date_parts),
                        "is_directory": is_directory,
                        "permissions": permissions
                    })
                
                return {
                    "job_id": job_id,
                    "exp_name": run.get("exp_name"),  # Keep for display purposes
                    "current_path": path,
                    "run_dir": run_dir,
                    "files": files
                }
                
            except Exception as e:
                return {"error": f"Failed to list directory: {str(e)}"}
                
        finally:
            conn.close()

    @app.get("/api/jobs/{job_id}/download")
    def api_download_file(job_id: str, file_path: str):
        """Download a specific file from a job's run directory."""
        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            from .registry import Registry
            import tempfile
            import os
            import posixpath
            from fastapi.responses import FileResponse
            
            remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
            reg = Registry(ssh_user, ssh_host, remote_dir, cfg.get("_local_root"))
            run = reg.find_run(job_id=job_id)
            
            if not run:
                raise ValueError(f"No run found for job_id {job_id}")
            
            run_dir = run.get("run_dir")
            if not run_dir:
                raise ValueError(f"No run directory found for job_id {job_id}")
            
            # Construct full remote file path using posixpath for remote paths
            remote_file_path = posixpath.join(run_dir, file_path.lstrip('/'))
            
            # Create a temporary local file
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_path = temp_file.name
            
            try:
                # Download the file to the temporary location
                conn.get_file(remote_file_path, temp_path)
                
                # Get the filename for the response
                filename = os.path.basename(file_path)
                
                # Return the file as a download
                return FileResponse(
                    temp_path,
                    filename=filename,
                    media_type='application/octet-stream'
                )
            except Exception as e:
                # Clean up temp file if download failed
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise ValueError(f"Failed to download file: {str(e)}")
                
        finally:
            conn.close()

    # ---------------------------------------------------------------------
    # Config endpoints (view + patch run section)
    # ---------------------------------------------------------------------

    @app.get("/api/config")
    def api_get_config():
        """Return the *run* section so the UI can modify grid / experiments."""
        return cfg.get("run", {})

    @app.get("/api/config/full")
    def api_get_full_config():
        """Return the full config including remote, files, slurm sections."""
        return {
            "run": cfg.get("run", {}),
            "remote": cfg.get("remote", {}),
            "files": cfg.get("files", {}),
            "slurm": cfg.get("slurm", {})
        }

    @app.patch("/api/config")
    def api_patch_config(payload: dict):
        """Merge the provided dict into cfg["run"]. Expect JSON payload.
        Supports updating *grid* or *experiments* keys.
        """
        if not isinstance(payload, dict):
            raise ValueError("Payload must be an object")
        run_cfg = cfg.setdefault("run", {})
        run_cfg.update(payload)
        # When run_cfg changes, we may want to reset cached values, but in-memory
        # cfg is used for future submissions, so this is fine. Persisting back to
        # disk is out of scope for now.
        return {"detail": "updated"}

    @app.patch("/api/config/full")
    def api_patch_full_config(payload: dict):
        """Update the full config including remote, files, slurm sections."""
        if not isinstance(payload, dict):
            raise ValueError("Payload must be an object")
        
        # Update each section
        for section in ['run', 'remote', 'files', 'slurm']:
            if section in payload:
                cfg.setdefault(section, {}).update(payload[section])
        
        return {"detail": "full config updated"}

    # ---------------------------------------------------------------------
    # WebSocket: live log streaming
    # ---------------------------------------------------------------------

    @app.websocket("/ws/logs/{job_id}")
    async def ws_logs(websocket: WebSocket, job_id: str):
        await websocket.accept()
        conn = _open_conn(ssh_host, ssh_user, ssh_port, password, key_filename)
        try:
            remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
            reg = Registry(ssh_user, ssh_host, remote_dir, cfg.get("_local_root"))
            run = reg.find_run(job_id=job_id)
            if not run:
                await websocket.send_text(f"No run found for job {job_id}")
                await websocket.close()
                return
            log_file = run.get("log_file")
            if not log_file:
                await websocket.send_text("No log file")
                await websocket.close()
                return

            import asyncio, anyio
            loop = asyncio.get_running_loop()

            def _stream():
                try:
                    for line in conn.stream_tail(log_file, from_start=False, lines=100):
                        if websocket.application_state != WebSocketState.CONNECTED:
                            break
                        asyncio.run_coroutine_threadsafe(websocket.send_text(line), loop)
                except Exception as e:
                    asyncio.run_coroutine_threadsafe(websocket.send_text(f"[ERROR] {e}"), loop)
            try:
                await anyio.to_thread.run_sync(_stream)
            except WebSocketDisconnect:
                pass
        finally:
            conn.close()
            try:
                await websocket.close()
            except Exception:
                pass

    # ---------------------------------------------------------------------
    # Front-end: serve a single-file dashboard fed by the above APIs.
    # ---------------------------------------------------------------------

    static_dir = Path(__file__).parent / "static"
    index_file = static_dir / "dashboard.html"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index_page():
        return FileResponse(index_file)

    return app


# -----------------------------------------------------------------------------
# Public entry point used by the CLI wrapper
# -----------------------------------------------------------------------------

def run_server(cfg, *, ssh_user: str, ssh_host: str, ssh_port: int = 22, password: str | None = None, key_filename: str | None = None, bind_host: str = "0.0.0.0", bind_port: int = 8000):
    """Blocking call: start the Uvicorn server (HTTP)."""

    app = create_app(
        cfg,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        password=password,
        key_filename=key_filename,
    )

    # Uvicorn's internals handle KeyboardInterrupt gracefully.
    uvicorn.run(app, host=bind_host, port=bind_port) 