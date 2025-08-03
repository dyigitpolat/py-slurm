from .connection import SSHConnection
from .registry import Registry
from .remote_utils import (
    _resolve_remote_path,
    _run_state_from_markers,
    _squeue_state,
)


def status(conn: SSHConnection, cfg, only_unfetched: bool = True):
    """Print table with current status of tracked runs."""
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    reg = Registry(conn.user, conn.host, remote_dir, cfg.get('_local_root'))
    runs = reg.unfetched_runs() if only_unfetched else reg.all_runs()

    rows = []
    for r in runs:
        job_id = r["job_id"]
        run_dir = r["run_dir"]
        # Prefer fast, reliable marker files written by the job script.  Only
        # fall back to `squeue` if markers yield UNKNOWN (e.g. job not started
        # or directory gone).
        state = _run_state_from_markers(conn, run_dir)
        if state == "UNKNOWN":
            sq = _squeue_state(conn, job_id)
            # Map Slurm COMPLETED → FINISHED for consistency with marker names.
            if sq == "COMPLETED":
                sq = "FINISHED"
            state = sq or state
        reg.update_run(job_id=job_id, state=state)
        rows.append((r["exp_name"], job_id, state))
    if not rows:
        print("(no runs)")
        return
    w1 = max(len(x[0]) for x in rows)
    w2 = max(len(x[1]) for x in rows)
    print(f"EXP NAME".ljust(w1) + "  " + "JOB ID".ljust(w2) + "  STATE")
    for exp, jid, st in rows:
        print(f"{exp.ljust(w1)}  {jid.ljust(w2)}  {st}")


__all__ = ["status"] 