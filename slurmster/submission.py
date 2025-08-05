import os
import posixpath
import time
from .connection import SSHConnection
from .remote_utils import _resolve_remote_path, _parse_job_id
from .utils import expand_grid, make_exp_name, substitute_placeholders
from .registry import Registry
from .env_setup import DEFAULT_SBATCH_OUTPUT


JOB_SCRIPT_TEMPLATE = """#!/bin/bash
{sbatch}
# Auto-added:
#SBATCH --chdir={remote_dir}

set -euo pipefail

RUN_DIR="{run_dir}"
mkdir -p "$RUN_DIR"
rm -f "$RUN_DIR/.pending"
 touch "$RUN_DIR/.running"

LOG_FILE="$RUN_DIR/stdout.log"

# Activate venv if present
if [ -d "{venv_dir}" ]; then
  source "{venv_dir}/bin/activate"
fi

# Execute user's command, tee stdout/stderr to file, preserve exit code
( {run_cmd} ) 2>&1 | tee -a "$LOG_FILE"
exit_code=${{PIPESTATUS[0]}}

rm -f "$RUN_DIR/.running"
 touch "$RUN_DIR/.finished"
echo $exit_code > "$RUN_DIR/.exitcode"
exit $exit_code
"""


def _make_exp_list(cfg):
    run_cfg = cfg["run"]
    if "experiments" in run_cfg and run_cfg["experiments"]:
        return list(run_cfg["experiments"])
    grid = run_cfg.get("grid")
    return expand_grid(grid)


def submit_all(
    conn: SSHConnection,
    cfg,
    user: str,
    host: str,
    monitor: bool = True,
    dependency_job_id: str | None = None,
):
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])

    # Guarantee base experiment directory exists with tilde correctly expanded.
    conn.mkdirs(remote_dir)
    conn.bash(f"mkdir -p {remote_dir}")
    venv_dir = posixpath.join(remote_dir, "venv")
    registry = Registry(user, host, remote_dir, cfg.get('_local_root'))

    exp_list = _make_exp_list(cfg)

    first_run_info = None  # (exp_name, job_id, run_dir)

    for params in exp_list:
        exp_name = make_exp_name(params)
        # Use $SLURM_JOB_ID so the directory name is unique per job and includes
        # the Slurm id. This variable is available inside the job script at
        # runtime.  We keep the placeholder in Python so the path still makes
        # sense when substituting into the script and user directives.
        run_dir_tpl = posixpath.join(remote_dir, "runs", f"{exp_name}_${{SLURM_JOB_ID}}")

        # prepare sbatch text with substitutions
        placeholders = dict(params)
        placeholders.update({
            "base_dir": remote_dir,  # new placeholder equals resolved base dir
            "remote_dir": remote_dir,
            "run_dir": run_dir_tpl,
        })

        sbatch_directives = cfg["slurm"]["directives"]
        # Ensure any necessary dependency (e.g. env_setup job) is respected so the
        # actual experiment only starts after environment preparation finished.
        if dependency_job_id:
            sbatch_directives = (
                sbatch_directives.rstrip() + f"\n#SBATCH --dependency=afterok:{dependency_job_id}"
            )
        if "--output=" not in sbatch_directives:
            sbatch_directives = sbatch_directives.strip() + "\n" + DEFAULT_SBATCH_OUTPUT

        sbatch_resolved = substitute_placeholders(sbatch_directives, placeholders)
        run_cmd_resolved = substitute_placeholders(cfg["run"]["command"], placeholders)

        # build and upload job script
        job_script_text = JOB_SCRIPT_TEMPLATE.format(
            sbatch=sbatch_resolved.strip(),
            remote_dir=remote_dir,
            run_dir=run_dir_tpl,
            venv_dir=venv_dir,
            run_cmd=run_cmd_resolved.strip(),
        )
        job_path = posixpath.join(remote_dir, "jobs", f"{exp_name}.sh")
        _local = _write_temp(job_script_text)

        # Transfer job script and verify it exists & is non-empty on the remote side.
        try:
            conn.put_file(local_path=_local, remote_path=job_path)

            # Sanity-check: file should exist and be non-zero size.  This catches
            # silent SFTP issues that would otherwise surface later as confusing
            # “Batch script is empty!” errors from sbatch.
            rc, _out, _err = conn.bash(f"test -s {job_path}")
            if rc != 0:
                raise RuntimeError(
                    f"Remote job script {job_path} appears to be missing or empty after upload."
                )
        finally:
            try:
                os.remove(_local)
            except Exception:
                pass

        # Make script executable; directory creation and marker file will be
        # handled after we know the actual job id.
        conn.bash(f"chmod +x {job_path}")

        # sbatch submit (no need to `cd`; job script has absolute path and --chdir directive)
        rc, out, err = conn.bash(f"sbatch {job_path}")
        if rc != 0:
            raise RuntimeError(f"sbatch failed for {exp_name}: {err or out}")
        job_id = _parse_job_id(out)

        # Concrete run_dir and log paths with the real job id
        final_run_dir = posixpath.join(remote_dir, "runs", f"{exp_name}_{job_id}")
        conn.bash(f"mkdir -p {final_run_dir} && touch {final_run_dir}/.pending")

        # store in registry
        registry.add_run({
            "exp_name": exp_name,
            "params": params,
            "job_id": job_id,
            "run_dir": final_run_dir,
            "log_file": posixpath.join(final_run_dir, "stdout.log"),
            "fetched": False,
            "state": "PENDING",
            "submitted_at": int(time.time()),
        })

        print(f"submitted {exp_name} as job {job_id}")

        # remember first run for potential monitoring later
        if first_run_info is None:
            first_run_info = (exp_name, job_id, final_run_dir)

    # After all submissions, optionally start streaming only the *first* job.
    if monitor and first_run_info:
        exp_name, job_id, run_dir = first_run_info
        print(f"--- streaming {exp_name} ({job_id}) ---")
        try:
            for line in conn.stream_tail(posixpath.join(run_dir, "stdout.log"), from_start=False, lines=50):
                print(line, flush=True)
        except KeyboardInterrupt:
            print("stopped monitoring (Ctrl-C). You can re-attach later with 'slurmster monitor --job <job_id>'")

    return True


def _write_temp(content):
    import tempfile, uuid
    path = os.path.join(tempfile.gettempdir(), f"slurmster_{uuid.uuid4().hex}.sh")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


__all__ = ["submit_all"] 