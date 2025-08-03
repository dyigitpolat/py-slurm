from .connection import SSHConnection
from .registry import Registry
from .remote_utils import _resolve_remote_path


def cancel(conn: SSHConnection, cfg, exp_name=None, job_id=None):
    """Cancel a running Slurm job and update local registry."""
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    reg = Registry(conn.user, conn.host, remote_dir, cfg.get('_local_root'))
    run = reg.find_run(exp_name=exp_name, job_id=job_id)
    if not run:
        raise SystemExit("No matching run in registry")
    jid = run["job_id"]
    rc, out, err = conn.bash(f"scancel {jid}")
    if rc != 0:
        raise SystemExit(f"scancel failed: {err or out}")
    reg.update_run(job_id=jid, state="CANCELLED")
    print(f"cancelled {run['exp_name']} (job {jid})")


__all__ = ["cancel"] 