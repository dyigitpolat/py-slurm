import os
import getpass
import argparse
from .connection import SSHConnection
from .core import (
    load_config,
    setup_remote_env,
    submit_all,
    monitor,
    status,
    fetch,
    cancel,
    cancel_all,
)

def _password_from_env(env):
    if not env:
        return None
    return os.environ.get(env)

def main():
    parser = argparse.ArgumentParser(prog="slurmster", description="Minimal Slurm experiment runner in Python")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument("--user", required=True, help="SSH username")
    parser.add_argument("--host", required=True, help="SSH host")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default 22)")
    parser.add_argument("--password-env", default=None, help="Name of env var containing SSH password")
    parser.add_argument("--key", default=None, help="Path to SSH key file (optional)")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_submit = sub.add_parser("submit", help="Submit all experiments (grid or list)")
    p_submit.add_argument("--no-monitor", action="store_true", help="Do not auto-stream logs after submit")

    p_monitor = sub.add_parser("monitor", help="Stream logs for a single run")
    p_monitor.add_argument("--job", required=True, help="Job ID to follow")
    p_monitor.add_argument("--from-start", action="store_true", help="Stream from beginning (default: last 100 lines)")
    p_monitor.add_argument("--lines", type=int, default=100, help="Number of trailing lines when attaching (default 100)")

    p_status = sub.add_parser("status", help="Show status of runs")
    p_status.add_argument("--all", action="store_true", help="Show all runs (default: only non-fetched)")

    p_fetch = sub.add_parser("fetch", help="Fetch finished runs to local workspace")
    p_fetch.add_argument("--job", help="Only fetch a single job by ID")
    p_fetch.add_argument("--all", action="store_true", help="Fetch all finished jobs (default behavior)")

    p_cancel = sub.add_parser("cancel", help="Cancel jobs")
    g2 = p_cancel.add_mutually_exclusive_group(required=True)
    g2.add_argument("--job", help="Cancel a single job by ID")
    g2.add_argument("--all", action="store_true", help="Cancel all jobs tracked in this base directory")

    p_gui = sub.add_parser("gui", help="Launch interactive web UI")
    p_gui.add_argument("--gui-port", dest="gui_port", type=int, default=8000, help="HTTP port for web UI (default 8000)")
    p_gui.add_argument("--gui-bind", dest="gui_bind", default="0.0.0.0", help="Bind interface (default 0.0.0.0)")
    p_gui.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")

    args = parser.parse_args()

    cfg = load_config(args.config)
    # Always place .slurmster workspace next to the YAML config file
    _cfg_dir = os.path.dirname(os.path.abspath(args.config))
    cfg["_local_root"] = os.path.join(_cfg_dir, ".slurmster")

    # Prepare push-file mapping (local absolute path, remote relative path)
    push_entries = []
    for entry in cfg.get("files", {}).get("push", []):
        if os.path.isabs(entry):
            local_abs = entry
            remote_rel = os.path.basename(entry)
        else:
            local_abs = os.path.abspath(os.path.join(_cfg_dir, entry))
            remote_rel = entry
        push_entries.append((local_abs, remote_rel))
    cfg["_push_mapping"] = push_entries

    # Special case: we open the SSH connection lazily for GUI so the server can
    # create fresh connections per request. For all other commands we connect
    # immediately here.
    if args.cmd != "gui":
        password = _password_from_env(args.password_env)
        if not password and not args.key:
            password = getpass.getpass(f"SSH password for {args.user}@{args.host}: ")

        conn = SSHConnection(host=args.host, user=args.user, port=args.port, password=password, key_filename=args.key).connect()

    try:
        if args.cmd == "gui":
            # Password handling (prompt only once here)
            password = _password_from_env(args.password_env)
            if not password and not args.key:
                password = getpass.getpass(f"SSH password for {args.user}@{args.host}: ")
            from .gui_server import run_server
            import webbrowser, threading

            if not args.no_browser:
                threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.gui_port}")).start()
            run_server(
                cfg,
                ssh_user=args.user,
                ssh_host=args.host,
                ssh_port=args.port,
                password=password,
                key_filename=args.key,
                bind_host=args.gui_bind,
                bind_port=args.gui_port,
            )
        elif args.cmd == "submit":
            # Automatically locate env_setup.sh in the same directory as the YAML config (if present)
            config_dir = os.path.dirname(os.path.abspath(args.config))
            env_script = os.path.join(config_dir, "env_setup.sh")
            if os.path.exists(env_script):
                env_script_path = env_script
            else:
                # Fall back to the script bundled with the package (slurmster/env_setup.sh)
                bundled_script = os.path.join(os.path.dirname(__file__), "env_setup.sh")
                env_script_path = bundled_script if os.path.exists(bundled_script) else None
            _venv_dir, dep_job_id = setup_remote_env(conn, cfg, env_script_path=env_script_path)
            if dep_job_id:
                from .core import wait_for_job
                wait_for_job(conn, dep_job_id)
            submit_all(
                conn,
                cfg,
                user=args.user,
                host=args.host,
                monitor=(not args.no_monitor),
                dependency_job_id=dep_job_id,
            )
        elif args.cmd == "monitor":
            monitor(conn, cfg, job_id=args.job, from_start=args.from_start, lines=args.lines)
        elif args.cmd == "status":
            status(conn, cfg, only_unfetched=(not args.all))
        elif args.cmd == "fetch":
            if args.job:
                fetch(conn, cfg, job_id=args.job)
            else:
                fetch(conn, cfg)  # fetch all by default
        elif args.cmd == "cancel":
            if getattr(args, "all", False):
                cancel_all(conn, cfg)
            else:
                cancel(conn, cfg, job_id=args.job)
    finally:
        if args.cmd != "gui":
            conn.close()
