# slurmster

A minimal Python tool to run parameter-grid experiments on a Slurm cluster with persistent SSH, log streaming, and simple YAML configs.

## Install

```bash
pip install slurmster
```

![Slurmster GUI](https://github.com/dyigitpolat/slurmster/raw/main/images/gui.png)

## Features

- CLI with subcommands: `submit`, `monitor`, `status`, `fetch`, `cancel`, `gui`
- YAML config (explicitly provided via `--config`)
- Persistent SSH connection for low latency
- Per-run working directories on the remote side
- Automatic log redirection to `stdout.log` inside each run directory
- Live log streaming (and re-attach later)
- Local workspace to track runs and "fetched" state
- Cancel jobs from local machine
- Web-based GUI for easy management

## CLI Usage

All commands follow this pattern:

```bash
slurmster --config <config.yaml> --user <username> --host <hostname> [options] <command>
```

### Basic Commands

**Submit experiments:**
```bash
slurmster --config config.yaml --user myuser --host myhost submit
```

**Monitor logs:**
```bash
# Monitor by job ID:
slurmster --config config.yaml --user myuser --host myhost monitor --job 1234567
```

**Check status:**
```bash
slurmster --config config.yaml --user myuser --host myhost status
```

**Fetch completed runs:**
```bash
# Fetch all completed runs:
slurmster --config config.yaml --user myuser --host myhost fetch
# Or fetch a specific job:
slurmster --config config.yaml --user myuser --host myhost fetch --job 1234567
```

**Cancel jobs:**
```bash
# Cancel specific job:
slurmster --config config.yaml --user myuser --host myhost cancel --job 1234567
# or cancel all:
slurmster --config config.yaml --user myuser --host myhost cancel --all
```

### Additional Options

- `--password-env ENV_VAR`: Use password from environment variable
- `--key /path/to/key`: Use SSH key file instead of password
- `--port 22`: Specify SSH port (default: 22)

For submit:
- `--no-monitor`: Don't automatically start monitoring after submission

For monitor:
- `--from-start`: Stream from beginning instead of last 100 lines
- `--lines N`: Number of trailing lines when attaching (default: 100)

For status:
- `--all`: Show all runs (default: only non-fetched)

For fetch:
- `--job <job_id>`: Only fetch a specific job by ID

## Configuration File

Create a YAML config file (see `example/config.yaml`):

```yaml
remote:
  base_dir: ~/experiments            # remote working root

files:
  push:
    - example/train.py               # any code/data files you need on remote
  fetch:
    - "model.pth"                   # optional; if omitted we fetch the entire run dir
    - "log.txt"

slurm:
  directives: |                      # SBATCH lines; placeholders allowed
    #SBATCH --job-name={base_dir}
    #SBATCH --partition=gpu
    #SBATCH --time=00:10:00
    #SBATCH --cpus-per-gpu=40
    #SBATCH --nodes=1
    #SBATCH --gres=gpu:1
    #SBATCH --mem=32G

run:
  command: |                         # your run command; placeholders allowed
    source venv/bin/activate
    python example/train.py --lr {lr} --epochs {epochs} --save_model "{run_dir}/model.pth" --log_file "{run_dir}/log.txt"

  # ONE of the following:
  grid:
    lr: [0.1, 0.01, 0.001]
    epochs: [1, 2, 5, 10]
  # experiments:
  #   - { lr: 0.1, epochs: 1 }
  #   - { lr: 0.001, epochs: 10 }
```

### Placeholders

- `{base_dir}`: resolved remote base directory (e.g. `/home/you/experiments`)
- Any run parameter placeholder, e.g. `{lr}`, `{epochs}`
- `{remote_dir}`: the configured `remote.base_dir`
- `{run_dir}`: the per-run directory (under `remote.base_dir/runs/{exp_name}`)

## Local workspace

Under the **`.slurmster` directory next to your `config.yaml`** (`<config-dir>/.slurmster/<user>@<host>/<sanitized-remote-base>`), we store:
- `runs.json` — run registry (job id, exp name, fetched flag, etc.)
- `results/<exp_name>_<job_id>/...` — fetched run directories

## GUI Usage

For a more user-friendly experience, you can use the web-based GUI:

```bash
slurmster --config config.yaml --user myuser --host myhost gui
```

Additional GUI options:
- `--gui-port 8000`: Set the HTTP port (default: 8000)
- `--gui-bind 0.0.0.0`: Set the bind interface (default: 0.0.0.0)
- `--no-browser`: Don't automatically open browser

The GUI provides:

**Configuration Management:**
- View and edit your current configuration
- See resolved placeholders and SLURM directives
- Modify files to push/fetch and run commands

**Job Submission:**
- Submit single jobs with custom parameters
- Submit grid jobs with parameter combinations
- Real-time parameter validation

**Job Monitoring:**
- View all jobs with their current status
- Monitor and browse job outputs in real-time
- Access job logs directly in the browser

**Bulk Operations:**
- Fetch all completed jobs at once
- Cancel multiple jobs
- Track job progress and completion status

The GUI automatically opens in your browser at `http://localhost:8000` (or your specified port) and provides an intuitive interface for all slurmster functionality.

## License

MIT — see LICENSE.
