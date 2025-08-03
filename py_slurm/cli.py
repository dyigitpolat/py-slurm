import os
import getpass
import argparse
from .connection import SSHConnection
from .core import load_config, setup_remote_env, submit_all, monitor, status, fetch, cancel

def _password_from_env(env):
    if not env:
        return None
    return os.environ.get(env)

def main():
    parser = argparse.ArgumentParser(prog="py-slurm", description="Minimal Slurm experiment runner in Python")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument("--user", required=True, help="SSH username")
    parser.add_argument("--host", required=True, help="SSH host")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default 22)")
    parser.add_argument("--password-env", default=None, help="Name of env var containing SSH password")
    parser.add_argument("--key", default=None, help="Path to SSH key file (optional)")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_submit = sub.add_parser("submit", help="Submit all experiments (grid or list)")
    p_submit.add_argument("--no-monitor", action="store_true", help="Do not auto-stream logs after submit")

    p_monitor = sub.add_parser("monitor", help="Stream logs for a single run")
    g = p_monitor.add_mutually_exclusive_group(required=True)
    g.add_argument("--exp", help="Experiment name to follow")
    g.add_argument("--job", help="Job ID to follow")
    p_monitor.add_argument("--from-start", action="store_true", help="Stream from beginning (default: last 100 lines)")
    p_monitor.add_argument("--lines", type=int, default=100, help="Number of trailing lines when attaching (default 100)")

    p_status = sub.add_parser("status", help="Show status of runs")
    p_status.add_argument("--all", action="store_true", help="Show all runs (default: only non-fetched)")

    p_fetch = sub.add_parser("fetch", help="Fetch finished runs to local workspace")
    p_fetch.add_argument("--exp", help="Only fetch a single experiment by name")

    p_cancel = sub.add_parser("cancel", help="Cancel a job")
    g2 = p_cancel.add_mutually_exclusive_group(required=True)
    g2.add_argument("--exp", help="Experiment name to cancel")
    g2.add_argument("--job", help="Job ID to cancel")

    args = parser.parse_args()

    cfg = load_config(args.config)

    password = _password_from_env(args.password_env)
    if not password and not args.key:
        password = getpass.getpass(f"SSH password for {args.user}@{args.host}: ")

    conn = SSHConnection(host=args.host, user=args.user, port=args.port, password=password, key_filename=args.key).connect()

    try:
        if args.cmd == "submit":
            setup_remote_env(conn, cfg)
            submit_all(conn, cfg, user=args.user, host=args.host, monitor=(not args.no_monitor))
        elif args.cmd == "monitor":
            monitor(conn, cfg, exp_name=args.exp, job_id=args.job, from_start=args.from_start, lines=args.lines)
        elif args.cmd == "status":
            status(conn, cfg, only_unfetched=(not args.all))
        elif args.cmd == "fetch":
            fetch(conn, cfg, exp_name=args.exp)
        elif args.cmd == "cancel":
            cancel(conn, cfg, exp_name=args.exp, job_id=args.job)
    finally:
        conn.close()
