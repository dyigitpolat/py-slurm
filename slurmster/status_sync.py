"""
Comprehensive status synchronization between remote SLURM system and local registry.

This module provides functionality to:
1. Discover all jobs on the remote system (including those not in local registry)
2. Update status for all jobs
3. Synchronize remote job information with local registry
"""

import re
import posixpath
from typing import List, Dict, Any, Optional
from .connection import SSHConnection
from .registry import Registry
from .remote_utils import (
    _resolve_remote_path,
    _run_state_from_markers,
    _squeue_state,
)


def discover_remote_jobs(conn: SSHConnection, remote_dir: str) -> List[Dict[str, Any]]:
    """
    Discover all job run directories on the remote system.
    
    This scans the runs/ directory for all job directories and extracts
    job information from directory names and marker files.
    
    Returns:
        List of job dictionaries with discovered information
    """
    runs_dir = posixpath.join(remote_dir, "runs")
    
    # List all directories in the runs folder
    rc, out, err = conn.bash(f"find {runs_dir} -maxdepth 1 -type d -name '*_*' 2>/dev/null || true")
    if rc != 0 or not out.strip():
        return []
    
    discovered_jobs = []
    run_dirs = [d.strip() for d in out.strip().split('\n') if d.strip()]
    
    for run_dir in run_dirs:
        # Extract job info from directory name: exp_name_jobid
        dir_name = posixpath.basename(run_dir)
        
        # Try to parse the directory name to extract exp_name and job_id
        # Format should be: exp_param1_value1_param2_value2_JOBID
        match = re.match(r'^(.+)_(\d+)$', dir_name)
        if not match:
            continue
            
        exp_name_part, job_id = match.groups()
        
        # Get current state from markers
        state = _run_state_from_markers(conn, run_dir)
        if state == "UNKNOWN":
            # Fall back to squeue if markers don't give us info
            sq = _squeue_state(conn, job_id)
            if sq == "COMPLETED":
                sq = "FINISHED"
            state = sq or "UNKNOWN"
        
        # Try to parse experiment parameters from the exp_name
        params = _parse_exp_name(exp_name_part)
        
        # Check if results have been fetched (look for local directory)
        # This will be updated later when we check against the registry
        
        job_info = {
            "exp_name": exp_name_part,
            "job_id": job_id,
            "run_dir": run_dir,
            "log_file": posixpath.join(run_dir, "stdout.log"),
            "state": state,
            "params": params,
            "fetched": False,  # Will be updated when syncing with registry
            "submitted_at": None,  # Will be filled from registry if available
        }
        
        discovered_jobs.append(job_info)
    
    return discovered_jobs


def _parse_exp_name(exp_name: str) -> Dict[str, str]:
    """
    Parse experiment name to extract parameters.
    
    Expected format: exp_param1_value1_param2_value2
    """
    if not exp_name.startswith("exp_"):
        return {}
    
    parts = exp_name[4:].split("_")
    if len(parts) % 2 != 0:
        # Cannot form key/value pairs reliably
        return {}
    
    return {parts[i]: parts[i + 1] for i in range(0, len(parts), 2)}


def sync_status_comprehensive(conn: SSHConnection, cfg) -> List[Dict[str, Any]]:
    """
    Perform comprehensive status synchronization.
    
    This function:
    1. Discovers all jobs on the remote system
    2. Merges with existing local registry
    3. Updates status for all jobs
    4. Saves updated information to local registry
    
    Returns:
        List of all jobs with updated status information
    """
    remote_dir = _resolve_remote_path(conn, cfg["remote"]["base_dir"])
    reg = Registry(conn.user, conn.host, remote_dir, cfg.get('_local_root'))
    
    # Get existing jobs from local registry
    existing_jobs = {job.get("job_id"): job for job in reg.all_runs() if job.get("job_id")}
    
    # Discover all jobs on remote system
    discovered_jobs = discover_remote_jobs(conn, remote_dir)
    
    # Merge discovered jobs with existing registry
    all_jobs = []
    
    for discovered_job in discovered_jobs:
        job_id = discovered_job["job_id"]
        
        if job_id in existing_jobs:
            # Update existing job with latest status
            existing_job = existing_jobs[job_id]
            
            # Preserve information from registry
            discovered_job["fetched"] = existing_job.get("fetched", False)
            discovered_job["submitted_at"] = existing_job.get("submitted_at")
            
            # Update with fresh status information
            reg.update_run(
                job_id=job_id,
                state=discovered_job["state"],
                run_dir=discovered_job["run_dir"],
                log_file=discovered_job["log_file"],
                params=discovered_job["params"] or existing_job.get("params", {}),
            )
            
            # Use the updated job info
            final_job = dict(existing_job)
            final_job.update({
                "state": discovered_job["state"],
                "run_dir": discovered_job["run_dir"],
                "log_file": discovered_job["log_file"],
                "params": discovered_job["params"] or existing_job.get("params", {}),
            })
            all_jobs.append(final_job)
            
            # Remove from existing_jobs to track what we've processed
            del existing_jobs[job_id]
        else:
            # New job not in registry - add it
            reg.add_run(discovered_job)
            all_jobs.append(discovered_job)
    
    # Handle jobs that are in registry but not found on remote
    # (they might be very old or cleaned up)
    for remaining_job in existing_jobs.values():
        # Update status for jobs still in registry but not found on remote
        job_id = remaining_job.get("job_id")
        if job_id:
            # Try to get status from squeue
            sq = _squeue_state(conn, job_id)
            if sq == "COMPLETED":
                sq = "FINISHED"
            
            if sq:
                remaining_job["state"] = sq
                reg.update_run(job_id=job_id, state=sq)
            elif remaining_job.get("state") in ["PENDING", "RUNNING"]:
                # Job was running/pending but not found - might be completed or failed
                remaining_job["state"] = "UNKNOWN"
                reg.update_run(job_id=job_id, state="UNKNOWN")
        
        all_jobs.append(remaining_job)
    
    return all_jobs


def status_check_and_update(conn: SSHConnection, cfg, only_unfetched: bool = True) -> List[Dict[str, Any]]:
    """
    Enhanced status check that discovers new jobs and updates all statuses.
    
    This is an enhanced version of the original status function that:
    1. Performs comprehensive remote discovery
    2. Updates local registry with new findings
    3. Returns structured data instead of printing
    
    Args:
        conn: SSH connection to remote system
        cfg: Configuration dictionary
        only_unfetched: If True, only return unfetched jobs (for compatibility)
        
    Returns:
        List of job dictionaries with current status
    """
    # Perform comprehensive sync
    all_jobs = sync_status_comprehensive(conn, cfg)
    
    # Filter based on only_unfetched flag for compatibility
    if only_unfetched:
        return [job for job in all_jobs if not job.get("fetched", False)]
    else:
        return all_jobs


__all__ = [
    "discover_remote_jobs", 
    "sync_status_comprehensive", 
    "status_check_and_update"
]