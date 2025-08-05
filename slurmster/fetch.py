import os
from .connection import SSHConnection
from .registry import Registry
from .remote_utils import _resolve_remote_path, _run_state_from_markers


def fetch(conn: SSHConnection, cfg, job_id=None):
    """Download finished run directories from the cluster."""
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    reg = Registry(conn.user, conn.host, remote_dir, cfg.get('_local_root'))
    
    if job_id:
        # Fetch specific job by job_id
        run = reg.find_run(job_id=job_id)
        if not run:
            raise ValueError(f"No run found for job_id {job_id}")
        runs = [run]
    else:
        # Fetch all runs (default behavior)
        runs = reg.all_runs()

    for r in runs:
        if r.get("fetched"):
            continue
        state = _run_state_from_markers(conn, r["run_dir"])
        if state != "FINISHED":
            continue

        dest = os.path.join(reg.results_dir, f"{r['exp_name']}_{r['job_id']}")
        os.makedirs(dest, exist_ok=True)

        patterns = cfg["files"].get("fetch")
        if patterns:
            # TODO: support selective fetch; for now always get full run dir
            conn.get_dir(r["run_dir"], dest)
        else:
            conn.get_dir(r["run_dir"], dest)

        reg.update_run(job_id=r["job_id"], fetched=True, state="FINISHED")
        print(f"fetched into {dest}")


__all__ = ["fetch"] 