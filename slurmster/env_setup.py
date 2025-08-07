import os
import posixpath
import yaml
from typing import Optional, Tuple
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
    
    # env_setup is optional - if not specified, no environment setup will be performed
    cfg["run"].setdefault("env_setup", None)
    
    return cfg


def setup_remote_env(conn: SSHConnection, cfg, env_script_path: Optional[str] = None, stream_callback=None):
    """Prepare remote directories, upload source files, and **run** environment setup.

    Environment preparation (creating a virtualenv, installing deps) is
    executed directly on the login node. The script is idempotent – it checks 
    whether the venv already exists.

    Args:
        stream_callback: Optional callback function to receive streaming output

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

    env_job_id: Optional[str] = None

    # Upload & **run** env_setup.sh directly on login node (optional)
    if env_script_path and os.path.exists(env_script_path):
        remote_setup = posixpath.join(remote_dir, "env_setup.sh")
        conn.put_file(env_script_path, remote_setup)
        conn.bash(f"chmod +x {remote_setup}")

        # Run the environment preparation directly on the login node
        if stream_callback:
            # Stream output in real-time
            cmd = f"cd {remote_dir} && {remote_setup} 2>&1 | tee {remote_dir}/env_setup.out"
            rc = conn.run_with_streaming(cmd, stream_callback)
        else:
            # Run without streaming  
            rc, out, err = conn.bash(
                f"cd {remote_dir} && "
                f"{remote_setup} > {remote_dir}/env_setup.out 2> {remote_dir}/env_setup.err"
            )
        
        if rc != 0:
            raise RuntimeError(f"env_setup.sh failed (exit code {rc})")

        # Create marker file to indicate env setup completed successfully
        marker_file = posixpath.join(remote_dir, ".slurmster_env_setup")
        conn.bash(f"touch {marker_file}")
        if stream_callback:
            stream_callback("Environment setup completed successfully!")
        else:
            print(f"environment setup completed successfully")

    return venv_dir, env_job_id


def check_env_setup_marker(conn: SSHConnection, cfg) -> bool:
    """Check if environment setup marker file exists on remote."""
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    marker_file = posixpath.join(remote_dir, ".slurmster_env_setup")
    
    rc, _, _ = conn.bash(f"test -f {marker_file}")
    return rc == 0


def check_remote_dir_exists(conn: SSHConnection, cfg) -> bool:
    """Check if remote directory exists."""
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    
    rc, _, _ = conn.bash(f"test -d {remote_dir}")
    return rc == 0


__all__ = ["load_config", "setup_remote_env", "check_env_setup_marker", "check_remote_dir_exists"] 