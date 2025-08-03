import os
import posixpath
import time
import yaml
from .connection import SSHConnection
from .utils import expand_grid, make_exp_name, substitute_placeholders
from .registry import Registry

DEFAULT_SBATCH_OUTPUT = "#SBATCH --output={run_dir}/slurm-%j.out\n#SBATCH --error={run_dir}/slurm-%j.err"

def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # provide defaults
    cfg.setdefault("remote", {})
    cfg["remote"].setdefault("base_dir", "~/experiments")
    cfg["remote"].setdefault("venv_dir", "venv")
    cfg["remote"].setdefault("setup", {"create_venv": True, "requirements": None})

    cfg.setdefault("files", {})
    cfg["files"].setdefault("push", [])
    cfg["files"].setdefault("fetch", None)  # if None => fetch full run dir

    cfg.setdefault("slurm", {})
    cfg["slurm"].setdefault("directives", "#SBATCH --job-name={exp_name}\n" + DEFAULT_SBATCH_OUTPUT)

    cfg.setdefault("run", {})
    if "experiments" not in cfg["run"] and "grid" not in cfg["run"]:
        raise ValueError("config.run must provide either 'grid' or 'experiments'")
    if "command" not in cfg["run"]:
        raise ValueError("config.run.command is required")
    return cfg

# -------------------- Remote setup --------------------

def setup_remote_env(conn: SSHConnection, cfg):
    remote_dir = cfg["remote"]["base_dir"]
    venv_dir = posixpath.join(remote_dir, cfg["remote"]["venv_dir"])
    create_venv = cfg["remote"]["setup"].get("create_venv", True)
    requirements = cfg["remote"]["setup"].get("requirements")

    # ensure remote base exists
    conn.mkdirs(remote_dir)
    conn.mkdirs(posixpath.join(remote_dir, "runs"))
    conn.mkdirs(posixpath.join(remote_dir, "jobs"))

    # push files to remote base
    for f in cfg["files"]["push"]:
        conn.put_file(f, posixpath.join(remote_dir, f))

    if create_venv:
        conn.bash(f"cd {remote_dir} && python3 -m venv {venv_dir} || true")
        conn.bash(f"source {venv_dir}/bin/activate && python -m pip install --upgrade pip")
        if requirements and os.path.exists(requirements):
            conn.put_file(requirements, posixpath.join(remote_dir, requirements))
            conn.bash(f"source {venv_dir}/bin/activate && pip install -r {posixpath.join(remote_dir, requirements)}")
    return venv_dir

# -------------------- Job submit --------------------

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
    run = cfg["run"]
    if "experiments" in run and run["experiments"]:
        return list(run["experiments"])
    grid = run.get("grid")
    return expand_grid(grid)

def submit_all(conn: SSHConnection, cfg, user, host, monitor=True):
    remote_dir = cfg["remote"]["base_dir"]
    venv_dir = posixpath.join(remote_dir, cfg["remote"]["venv_dir"])
    registry = Registry(user, host, remote_dir)

    exp_list = _make_exp_list(cfg)

    for params in exp_list:
        exp_name = make_exp_name(params)
        run_dir = posixpath.join(remote_dir, "runs", exp_name)

        # prepare sbatch text with substitutions
        placeholders = dict(params)
        placeholders.update({
            "exp_name": exp_name,
            "remote_dir": remote_dir,
            "run_dir": run_dir,
        })

        sbatch_directives = cfg["slurm"]["directives"]
        if "--output=" not in sbatch_directives:
            sbatch_directives = sbatch_directives.strip() + "\n" + DEFAULT_SBATCH_OUTPUT

        sbatch_resolved = substitute_placeholders(sbatch_directives, placeholders)
        run_cmd_resolved = substitute_placeholders(cfg["run"]["command"], placeholders)

        # build and upload job script
        job_script_text = JOB_SCRIPT_TEMPLATE.format(
            sbatch=sbatch_resolved.strip(),
            remote_dir=remote_dir,
            run_dir=run_dir,
            venv_dir=venv_dir,
            run_cmd=run_cmd_resolved.strip(),
        )
        job_path = posixpath.join(remote_dir, "jobs", f"{exp_name}.sh")
        _local = _write_temp(job_script_text)
        try:
            conn.put_file(local_path=_local, remote_path=job_path)
        finally:
            try:
                os.remove(_local)
            except Exception:
                pass

        conn.bash(f"chmod +x {job_path} && mkdir -p {run_dir} && touch {run_dir}/.pending")

        # sbatch submit
        rc, out, err = conn.bash(f"cd {remote_dir} && sbatch {job_path}")
        if rc != 0:
            raise RuntimeError(f"sbatch failed for {exp_name}: {err or out}")
        job_id = _parse_job_id(out)

        # store in registry
        registry.add_run({
            "exp_name": exp_name,
            "params": params,
            "job_id": job_id,
            "run_dir": run_dir,
            "log_file": posixpath.join(run_dir, "stdout.log"),
            "fetched": False,
            "state": "PENDING",
            "submitted_at": int(time.time()),
        })

        print(f"submitted {exp_name} as job {job_id}")

        # optionally start streaming
        if monitor:
            print(f"--- streaming {exp_name} ({job_id}) ---")
            try:
                for line in conn.stream_tail(posixpath.join(run_dir, "stdout.log"), from_start=False, lines=50):
                    print(line, flush=True)
            except KeyboardInterrupt:
                print("stopped monitoring (Ctrl-C). You can re-attach later with 'py-slurm monitor --exp ...'")
    return True

def _parse_job_id(sbatch_output):
    # Expected: "Submitted batch job 123456"
    for tok in sbatch_output.strip().split():
        if tok.isdigit():
            return tok
    raise ValueError(f"Could not parse job id from: {sbatch_output!r}")

def _write_temp(content):
    import tempfile, uuid, os
    path = os.path.join(tempfile.gettempdir(), f"py_slurm_{uuid.uuid4().hex}.sh")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

# -------------------- Monitoring --------------------

def monitor(conn: SSHConnection, cfg, exp_name=None, job_id=None, from_start=False, lines=100):
    remote_dir = cfg["remote"]["base_dir"]
    reg = Registry(conn.user, conn.host, remote_dir)

    run = reg.find_run(exp_name=exp_name, job_id=job_id)
    if not run:
        raise SystemExit("No matching run found in local registry. Did you submit with this config/user/host?")

    log_file = run["log_file"]
    print(f"Following {log_file} on {conn.user}@{conn.host} ... (Ctrl-C to stop)")
    try:
        for line in conn.stream_tail(log_file, from_start=from_start, lines=lines):
            print(line, flush=True)
    except KeyboardInterrupt:
        print("Stopped monitoring. You can re-attach anytime.")

# -------------------- Status --------------------

def _remote_exists(conn, path):
    try:
        return conn.exists(path)
    except Exception:
        return False

def _run_state_from_markers(conn, run_dir):
    if _remote_exists(conn, posixpath.join(run_dir, ".finished")):
        return "FINISHED"
    if _remote_exists(conn, posixpath.join(run_dir, ".running")):
        return "RUNNING"
    if _remote_exists(conn, posixpath.join(run_dir, ".pending")):
        return "PENDING"
    return "UNKNOWN"

def _squeue_state(conn, job_id):
    rc, out, err = conn.bash(f"squeue -h -j {job_id} -o %T")
    if rc == 0:
        state = out.strip()
        return state or None
    return None

def status(conn: SSHConnection, cfg, only_unfetched=True):
    remote_dir = cfg["remote"]["base_dir"]
    reg = Registry(conn.user, conn.host, remote_dir)
    runs = reg.unfetched_runs() if only_unfetched else reg.all_runs()

    rows = []
    for r in runs:
        job_id = r["job_id"]
        run_dir = r["run_dir"]
        state = _run_state_from_markers(conn, run_dir)
        sq = _squeue_state(conn, job_id)
        state = sq or state
        reg.update_run(job_id=job_id, state=state)
        rows.append((r["exp_name"], job_id, state))
    if not rows:
        print("(no runs)")
        return
    w1 = max(len(x[0]) for x in rows)
    w2 = max(len(x[1]) for x in rows)
    print(f"{'EXP NAME'.ljust(w1)}  {'JOB ID'.ljust(w2)}  STATE")
    for exp, jid, st in rows:
        print(f"{exp.ljust(w1)}  {jid.ljust(w2)}  {st}")

# -------------------- Fetch --------------------

def fetch(conn: SSHConnection, cfg, exp_name=None):
    remote_dir = cfg["remote"]["base_dir"]
    reg = Registry(conn.user, conn.host, remote_dir)
    runs = reg.all_runs()
    if exp_name:
        runs = [r for r in runs if r["exp_name"] == exp_name]

    for r in runs:
        if r.get("fetched"):
            continue
        state = _run_state_from_markers(conn, r["run_dir"])
        if state != "FINISHED":
            continue

        dest = os.path.join(reg.results_dir, r["exp_name"])
        os.makedirs(dest, exist_ok=True)

        patterns = cfg["files"].get("fetch")
        if patterns:
            # Simplicity: fetch the entire run dir so everything is available locally.
            conn.get_dir(r["run_dir"], dest)
        else:
            conn.get_dir(r["run_dir"], dest)

        reg.update_run(exp_name=r["exp_name"], fetched=True, state="FINISHED")
        print(f"fetched into {dest}")

# -------------------- Cancel --------------------

def cancel(conn: SSHConnection, cfg, exp_name=None, job_id=None):
    remote_dir = cfg["remote"]["base_dir"]
    reg = Registry(conn.user, conn.host, remote_dir)
    run = reg.find_run(exp_name=exp_name, job_id=job_id)
    if not run:
        raise SystemExit("No matching run in registry")
    jid = run["job_id"]
    rc, out, err = conn.bash(f"scancel {jid}")
    if rc != 0:
        raise SystemExit(f"scancel failed: {err or out}")
    reg.update_run(job_id=jid, state="CANCELLED")
    print(f"cancelled {run['exp_name']} (job {jid})")
