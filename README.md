# py-slurm

A minimal Python tool to run parameter-grid experiments on a Slurm cluster with **persistent SSH**, **log streaming**, and **simple YAML configs** — inspired by a small Bash prototype.

## Highlights

- **CLI** with subcommands: `submit`, `monitor`, `status`, `fetch`, `cancel`
- **YAML** config (explicitly provided via `--config`)
- **Persistent SSH** connection for low latency
- **Per-run working directories** on the remote side
- **Automatic log redirection** to `stdout.log` inside each run directory
- **Live log streaming** (and re-attach later)
- **Local workspace** to track runs and “fetched” state
- **Cancel jobs** from local machine

## Install (editable)

```bash
cd py-slurm
pip install -e .
```

Or use a virtual environment first.

## Quick start

1) Prepare a config (see `example/config.yaml`).  
2) Submit jobs:

```bash
py-slurm submit --config example/config.yaml --user <remote_user> --host <remote_host> --password-env SLURM_PASS  # optional; otherwise you'll be prompted
```

3) Stream logs (auto-starts on submit unless `--no-monitor` is passed), or re-attach later:

```bash
py-slurm monitor --config example/config.yaml --user <remote_user> --host <remote_host> --exp exp_lr_0.01_epochs_5  # or --job <jobid>
```

4) Check status of **non-fetched** runs:

```bash
py-slurm status --config example/config.yaml --user <u> --host <h>
```

5) Fetch finished runs (downloads each run dir into your local workspace):

```bash
py-slurm fetch --config example/config.yaml --user <u> --host <h>
```

6) Cancel a job:

```bash
py-slurm cancel --config example/config.yaml --user <u> --host <h> --exp exp_lr_0.01_epochs_5
# or: --job 1234567
```

## YAML schema

```yaml
remote:
  base_dir: ~/experiments            # remote working root
  venv_dir: venv                     # created under base_dir
  setup:
    create_venv: true
    requirements: example/requirements.txt  # local path to upload & install (optional)

files:
  push:
    - example/train.py               # any code/data files you need on remote
  fetch:
    - "{exp_name}_model.pth"         # optional; if omitted we fetch the entire run dir
    - "{exp_name}_log.txt"

slurm:
  directives: |                      # SBATCH lines; placeholders allowed
    #SBATCH --job-name={exp_name}
    #SBATCH --partition=gpu
    #SBATCH --time=00:10:00
    #SBATCH --cpus-per-gpu=40
    #SBATCH --nodes=1
    #SBATCH --gres=gpu:1
    #SBATCH --mem=32G

run:
  command: |                         # your run command; placeholders allowed
    source venv/bin/activate
    python example/train.py --lr {lr} --epochs {epochs}           --save_model {exp_name}_model.pth --log_file {exp_name}_log.txt

  # ONE of the following:
  grid:
    lr: [0.1, 0.01, 0.001]
    epochs: [1, 2, 5, 10]
  # experiments:
  #   - { lr: 0.1, epochs: 1 }
  #   - { lr: 0.001, epochs: 10 }
```

### Placeholders

- `{exp_name}`: generated like `exp_lr_0.01_epochs_5`
- Any run parameter placeholder, e.g. `{lr}`, `{epochs}`
- `{remote_dir}`: the configured `remote.base_dir`
- `{run_dir}`: the per-run directory (under `remote.base_dir/runs/{exp_name}`)

## Local workspace

Under `~/.py_slurm/<user>@<host>/<sanitized-remote-base>`, we store:
- `runs.json` — run registry (job id, exp name, fetched flag, etc.)
- `results/<exp_name>/...` — fetched run directories

## License

MIT — see LICENSE.
