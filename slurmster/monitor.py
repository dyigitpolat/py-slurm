from .connection import SSHConnection
from .remote_utils import _resolve_remote_path
from .registry import Registry


def monitor(conn: SSHConnection, cfg, job_id=None, from_start=False, lines=100):
    """Stream logs of a running or finished experiment."""
    if not job_id:
        raise ValueError("job_id is required for monitoring")
        
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])  # ensure same key as submit
    reg = Registry(conn.user, conn.host, remote_dir, cfg.get('_local_root'))

    run = reg.find_run(job_id=job_id)
    if not run:
        raise SystemExit("No matching run found in local registry. Did you submit with this config/user/host?")

    log_file = run["log_file"]
    print(f"Following {log_file} on {conn.user}@{conn.host} ... (Ctrl-C to stop)")
    try:
        for line in conn.stream_tail(log_file, from_start=from_start, lines=lines):
            print(line, flush=True)
    except KeyboardInterrupt:
        print("Stopped monitoring. You can re-attach anytime.")


__all__ = ["monitor"] 