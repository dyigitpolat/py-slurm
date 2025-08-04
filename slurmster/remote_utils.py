import posixpath
import time
from .connection import SSHConnection


def _resolve_remote_path(conn: SSHConnection, path: str) -> str:
    """Expand a remote path that may start with "~" to the user home directory.

    The SFTP subsystem does *not* expand tildes, therefore paths like
    ``~/experiments`` would create a literal ``~/`` directory inside the remote
    home when used with SFTP methods.  We instead ask the remote shell for the
    user's ``$HOME`` and replace the leading tilde.
    """
    # Absolute paths (starting with '/') are fine as-is.
    if path.startswith("/"):
        return path

    # If the path is relative (does not start with '/' or '~'), treat it as
    # relative to the user's remote $HOME to obtain an absolute path.  This
    # prevents issues where we later use the same directory both in
    # `#SBATCH --chdir` and inside the job script (RUN_DIR), which would
    # otherwise duplicate the path (e.g. "mnist_test/mnist_test/...`).

    # Normal case: path starts with '~' (handled below) or is relative -> expand.
    if not path.startswith("~"):
        # Fetch remote $HOME once; fall back to path unchanged on failure.
        rc, out, _ = conn.bash("echo $HOME")
        if rc != 0:
            return path  # Could not determine, keep as-is.

        # Some clusters print greeting messages; take last non-empty absolute line.
        candidates = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("/")]
        if not candidates:
            return path  # unexpected format – leave unchanged

        home = candidates[-1]
        return posixpath.join(home, path)

    # --- existing tilde-expansion logic follows ---

    # Fetch remote $HOME once; fall back to path unchanged on failure.
    rc, out, _ = conn.bash("echo $HOME")
    if rc != 0:
        return path  # Could not determine, keep as-is.

    # Some clusters print greeting messages from .bashrc/.profile which pollute
    # stdout.  Take the last non-empty line that looks like an absolute path.
    candidates = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("/")]
    if not candidates:
        return path  # Fallback – unexpected format.

    home = candidates[-1]
    if path == "~":
        return home
    # Strip leading "~/" or "~" and join with remote home
    return posixpath.join(home, path.lstrip("~/"))


def _parse_job_id(sbatch_output: str) -> str:
    """Extract the numeric Slurm job id from ``sbatch`` output."""
    # Expected: "Submitted batch job 123456"
    for tok in sbatch_output.strip().split():
        if tok.isdigit():
            return tok
    raise ValueError(f"Could not parse job id from: {sbatch_output!r}")


def wait_for_job(conn: SSHConnection, job_id: str, poll_seconds: int = 10):
    """Block until the given Slurm job disappears from *squeue* (finished/cancelled)."""
    print(f"Waiting for job {job_id} to finish ... (Ctrl-C to abort)")
    while True:
        rc, out, _err = conn.bash(f"squeue -h -j {job_id}")
        # Determine if the job is still present in the squeue output.  Some
        # clusters prepend informational banners to every SSH command which
        # would otherwise trip the simple `bool(out.strip())` heuristic.
        # Therefore we explicitly look for the *job id* inside the output.
        # If the job id is absent (or the command itself failed), we assume the
        # job has left the queue.
        still_running = rc == 0 and str(job_id) in out
        if not still_running:
            break
        time.sleep(poll_seconds)
    print(f"Job {job_id} finished (left queue).")


def _remote_exists(conn: SSHConnection, path: str) -> bool:
    try:
        return conn.exists(path)
    except Exception:
        return False


def _run_state_from_markers(conn: SSHConnection, run_dir: str) -> str:
    # Highest priority: explicit cancel marker
    if _remote_exists(conn, posixpath.join(run_dir, ".cancelled")):
        return "CANCELLED"
    if _remote_exists(conn, posixpath.join(run_dir, ".finished")):
        return "FINISHED"
    if _remote_exists(conn, posixpath.join(run_dir, ".running")):
        return "RUNNING"
    if _remote_exists(conn, posixpath.join(run_dir, ".pending")):
        return "PENDING"
    return "UNKNOWN"


def _squeue_state(conn: SSHConnection, job_id: str):
    rc, out, err = conn.bash(f"squeue -h -j {job_id} -o %T")
    if rc == 0:
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        valid_states = {
            "PENDING",
            "RUNNING",
            "COMPLETED",
            "COMPLETING",
            "FAILED",
            "CANCELLED",
            "TIMEOUT",
            "SUSPENDED",
            "CONFIGURING",
            "RESIZING",
        }
        for ln in lines:
            tok = ln.split()[0].upper()
            if tok in valid_states:
                return tok
        return None
    return None


__all__ = [
    "_resolve_remote_path",
    "_parse_job_id",
    "wait_for_job",
    "_remote_exists",
    "_run_state_from_markers",
    "_squeue_state",
] 