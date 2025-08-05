import posixpath

from .connection import SSHConnection
from .registry import Registry
# Helper functions for remote state detection
from .remote_utils import _resolve_remote_path, _run_state_from_markers, _squeue_state


def cancel(conn: SSHConnection, cfg, job_id=None):
    """Cancel a running Slurm job and update local registry."""
    if not job_id:
        raise ValueError("job_id is required for canceling")
        
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    reg = Registry(conn.user, conn.host, remote_dir, cfg.get('_local_root'))
    run = reg.find_run(job_id=job_id)
    if not run:
        raise SystemExit("No matching run in registry")
    jid = run["job_id"]
    rc, out, err = conn.bash(f"scancel {jid}")
    if rc != 0:
        raise SystemExit(f"scancel failed: {err or out}")
    # Update registry and clean up remote run directory
    reg.update_run(job_id=jid, state="CANCELLED")
    # Mark run directory as cancelled
    run_dir = run.get("run_dir")
    if run_dir:
        conn.bash(f"touch {posixpath.join(run_dir, '.cancelled')}")
    print(f"cancelled {run['exp_name']} (job {jid}) and marked directory as cancelled")


# -----------------------------------------------------------------------------
# New helper: cancel_all
# -----------------------------------------------------------------------------


def cancel_all(conn: SSHConnection, cfg):
    """Cancel *all* jobs tracked in the local registry for this base directory.

    This iterates over the registry associated with the current *remote.base_dir*
    and issues an ``scancel`` for every recorded job id that has **not yet** been
    cancelled.  The registry is updated so subsequent ``slurmster status`` calls
    reflect the change.
    """

    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    reg = Registry(conn.user, conn.host, remote_dir, cfg.get('_local_root'))

    runs = reg.all_runs()
    if not runs:
        print("(no runs in registry)")
        return

    cancelled = 0
    skipped_finished = 0
    for run in runs:
        jid = run.get("job_id")
        run_dir = run.get("run_dir")

        # Skip entries with no job id or already cancelled
        if not jid or run.get("state") == "CANCELLED":
            continue

        # Determine current state via marker files first, fall back to squeue
        state = _run_state_from_markers(conn, run_dir) if run_dir else "UNKNOWN"
        if state == "UNKNOWN":
            sq = _squeue_state(conn, jid)
            if sq == "COMPLETED":
                sq = "FINISHED"
            state = sq or state

        # Update registry with the latest observed state
        if state and state != run.get("state"):
            reg.update_run(job_id=jid, state=state)

        # Skip cancelling finished jobs
        if state == "FINISHED":
            skipped_finished += 1
            print(f"skipped {run['exp_name']} (job {jid}) - already finished")
            continue

        rc, out, err = conn.bash(f"scancel {jid}")
        if rc == 0:
            reg.update_run(job_id=jid, state="CANCELLED")
            # Mark directory
            if run_dir:
                conn.bash(f"touch {posixpath.join(run_dir, '.cancelled')}")
            print(f"cancelled {run['exp_name']} (job {jid}) and marked directory as cancelled")
            cancelled += 1
        else:
            # scancel may fail if the job already left the queue; still mark the
            # run as CANCELLED locally so the registry is consistent.
            reg.update_run(job_id=jid, state="CANCELLED")
            if run_dir:
                conn.bash(f"touch {posixpath.join(run_dir, '.cancelled')}")
            print(f"could not cancel {jid}: {err or out} — marked directory as cancelled anyway")

    print(f"Cancelled {cancelled} job{'s' if cancelled != 1 else ''} (skipped {skipped_finished} finished run{'s' if skipped_finished != 1 else ''}).")


__all__ = ["cancel", "cancel_all"] 