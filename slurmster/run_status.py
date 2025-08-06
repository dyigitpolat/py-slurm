from .connection import SSHConnection
from .registry import Registry
from .remote_utils import (
    _resolve_remote_path,
    _run_state_from_markers,
    _squeue_state,
)
from .status_sync import status_check_and_update


def status(conn: SSHConnection, cfg, only_unfetched: bool = True):
    """Print table with current status of tracked runs.
    
    This enhanced version performs comprehensive status synchronization,
    discovering new jobs and updating all statuses.
    """
    # Use the enhanced status check that discovers new jobs
    runs = status_check_and_update(conn, cfg, only_unfetched=only_unfetched)
    
    if not runs:
        print("(no runs)")
        return
    
    # Build table for display
    rows = []
    for r in runs:
        exp_name = r.get("exp_name", "unknown")
        job_id = r.get("job_id", "unknown")
        state = r.get("state", "UNKNOWN")
        rows.append((exp_name, job_id, state))
    
    # Print formatted table
    w1 = max(len(x[0]) for x in rows)
    w2 = max(len(x[1]) for x in rows)
    print(f"EXP NAME".ljust(w1) + "  " + "JOB ID".ljust(w2) + "  STATE")
    for exp, jid, st in rows:
        print(f"{exp.ljust(w1)}  {jid.ljust(w2)}  {st}")
    
    # Show summary of discovered jobs
    total_jobs = len(runs)
    if not only_unfetched:
        print(f"\nFound {total_jobs} total job{'s' if total_jobs != 1 else ''}")
    else:
        fetched_jobs = sum(1 for r in runs if r.get("fetched", False))
        unfetched_jobs = total_jobs - fetched_jobs
        if unfetched_jobs != total_jobs:
            print(f"\nShowing {unfetched_jobs} unfetched job{'s' if unfetched_jobs != 1 else ''} ({fetched_jobs} fetched jobs hidden)")
        else:
            print(f"\nFound {total_jobs} unfetched job{'s' if total_jobs != 1 else ''}")


__all__ = ["status"] 