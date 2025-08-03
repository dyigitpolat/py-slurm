import os
import posixpath
import yaml
from .connection import SSHConnection
from .remote_utils import _resolve_remote_path, _parse_job_id


DEFAULT_SBATCH_OUTPUT = "#SBATCH --output={run_dir}/slurm-%j.out\n#SBATCH --error={run_dir}/slurm-%j.err"


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # provide defaults
    cfg.setdefault("remote", {})
    cfg["remote"].setdefault("base_dir", "~/experiments")

    cfg.setdefault("files", {})
    cfg["files"].setdefault("push", [])
    cfg["files"].setdefault("fetch", None)  # if None => fetch full run dir

    cfg.setdefault("slurm", {})
    cfg["slurm"].setdefault("directives", "#SBATCH --job-name={base_dir}\n" + DEFAULT_SBATCH_OUTPUT)

    cfg.setdefault("run", {})
    if "experiments" not in cfg["run"] and "grid" not in cfg["run"]:
        raise ValueError("config.run must provide either 'grid' or 'experiments'")
    if "command" not in cfg["run"]:
        raise ValueError("config.run.command is required")
    return cfg


def setup_remote_env(conn: SSHConnection, cfg, env_script_path: str | None = None):
    """Prepare remote directories, upload source files, and **schedule** environment setup.

    Heavy-weight environment preparation (creating a virtualenv, installing deps) is
    submitted to Slurm with *sbatch* so it runs on a compute node instead of the login
    node.  The job is idempotent – the script itself checks whether the venv already
    exists.

    Returns
    -------
    tuple[str, str|None]
        (venv_dir, env_setup_job_id)  – the second element is ``None`` if no
        env_setup script was found.
    """

    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    venv_dir = posixpath.join(remote_dir, "venv")

    # Create base directory hierarchy first.
    conn.mkdirs(remote_dir)
    conn.bash(
        f"mkdir -p {remote_dir} {posixpath.join(remote_dir, 'runs')} {posixpath.join(remote_dir, 'jobs')}"
    )

    # Push user-specified source files (e.g. training script, requirements.txt)
    push_map = cfg.get("_push_mapping")
    if push_map is None:
        # Backwards-compatibility: fall back to the plain list assuming paths are already correct
        push_map = [(f, f) for f in cfg["files"].get("push", [])]

    for local_path, remote_rel in push_map:
        dest = posixpath.join(remote_dir, remote_rel)
        # Ensure parent directory exists on remote in case nested paths are used
        conn.mkdirs(posixpath.dirname(dest))
        conn.put_file(local_path, dest)

    env_job_id: str | None = None

    # Upload & **submit** env_setup.sh as its own Slurm job (optional)
    if env_script_path and os.path.exists(env_script_path):
        remote_setup = posixpath.join(remote_dir, "env_setup.sh")
        conn.put_file(env_script_path, remote_setup)
        conn.bash(f"chmod +x {remote_setup}")

        # Submit the environment preparation as a separate job so it runs on a
        # compute node and we avoid blocking / spamming the login node.
        rc, out, err = conn.bash(
            "sbatch --job-name=env_setup "
            f"--chdir={remote_dir} "
            f"--output={remote_dir}/env_setup.out "
            f"--error={remote_dir}/env_setup.err "
            f"{remote_setup}"
        )
        if rc != 0:
            raise RuntimeError(f"sbatch failed for env_setup.sh: {err or out}")

        env_job_id = _parse_job_id(out)
        print(f"submitted env_setup.sh as job {env_job_id}")

    return venv_dir, env_job_id


__all__ = ["load_config", "setup_remote_env"] 