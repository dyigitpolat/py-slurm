import os
import re
import logging
import time
from typing import List, Dict, Any
from .connection import SSHConnection
from .config import Config

logger = logging.getLogger(__name__)

class JobManager:
    def __init__(self, ssh: SSHConnection, remote_dir: str):
        self.ssh = ssh
        self.remote_dir = remote_dir
    
    def _expand_grid(self, grid_params: List[str]) -> List[Dict[str, str]]:
        """Expand grid parameters into a list of parameter dictionaries."""
        # This is a simplified version of the bash grid expansion
        # In a real implementation, you'd want to use the same logic as the bash script
        params = []
        for param in grid_params:
            key, values = param.split(':', 1)
            for value in values.split(','):
                params.append({key: value})
        
        # Combine parameters into full experiment configurations
        experiments = []
        for i in range(len(params[0])):
            config = {}
            for param in params:
                key = next(iter(param))
                value = param[key]
                config[key] = value
            experiments.append(config)
        
        return experiments
    
    def _generate_job_name(self, experiment: Dict[str, str]) -> str:
        """Generate a safe job name from experiment parameters."""
        # Replace special characters with underscores
        safe_name = '_'.join([f"{k}_{v}" for k, v in experiment.items()])
        safe_name = re.sub(r'[^\w]', '_', safe_name)
        return f"exp_{safe_name}"
    
    def _generate_job_script(self, experiment: Dict[str, str], config: Config, job_name: str) -> str:
        """Generate the Slurm job script for a given experiment."""
        # Create the SBATCH directives
        sbatch_lines = []
        for directive in config.sbatch_directives:
            sbatch_lines.append(directive.format(exp_name=job_name))
        
        # Create the run command
        run_cmd = config.run_cmd
        for key, value in experiment.items():
            run_cmd = run_cmd.replace(f"{{{key}}}", value)
        run_cmd = run_cmd.replace("{exp_name}", job_name)
        
        # Generate the job script
        job_script = f"""#!/bin/bash
{chr(10).join(sbatch_lines)}
cd {self.remote_dir}
rm -f {job_name}.pending
touch {job_name}.running
{run_cmd}
rm -f {job_name}.running
touch {job_name}.finished
"""
        return job_script
    
    def _submit_job(self, job_script: str, job_name: str):
        """Submit a job to Slurm."""
        # Save the job script
        job_script_path = f"{self.remote_dir}/{job_name}.sh"
        with open(job_script_path, 'w') as f:
            f.write(job_script)
        
        # Submit the job
        self.ssh.run(f"cd {self.remote_dir} && chmod +x {job_name}.sh && sbatch {job_name}.sh")
    
    def submit_jobs(self, config: Config):
        """Submit all jobs based on the configuration."""
        # Expand grid parameters
        experiments = self._expand_grid(config.grid_params)
        
        # Create job scripts and submit
        for experiment in experiments:
            job_name = self._generate_job_name(experiment)
            job_script = self._generate_job_script(experiment, config, job_name)
            self._submit_job(job_script, job_name)
    
    def get_all_statuses(self) -> List[Dict[str, str]]:
        """Get the status of all jobs."""
        # Get all job marker files
        stdout, _, _ = self.ssh.run(f"cd {self.remote_dir} && ls -1 *.running *.finished *.pending 2>/dev/null")
        job_files = stdout.strip().split('\n')
        
        # Determine status for each job
        statuses = []
        for job_file in job_files:
            job_name = job_file.replace('.running', '').replace('.finished', '').replace('.pending', '')
            status = job_file.split('.')[-1]
            
            # Get job ID for running jobs
            job_id = None
            if status == 'running':
                # Get job ID from Slurm
                stdout, _, _ = self.ssh.run(f"cd {self.remote_dir} && squeue -u {self.ssh.username} | grep {job_name}")
                if stdout.strip():
                    job_id = stdout.strip().split()[0]
            
            statuses.append({
                'name': job_name,
                'status': status,
                'job_id': job_id
            })
        
        return statuses
    
    def fetch_job_outputs(self, job_name: str):
        """Fetch outputs for a finished job."""
        # Check if job is finished
        stdout, _, _ = self.ssh.run(f"cd {self.remote_dir} && ls -1 {job_name}.finished 2>/dev/null")
        if not stdout.strip():
            logger.warning(f"Job {job_name} is not finished, skipping")
            return
        
        # Fetch files
        for file_pattern in self.ssh.config.files_to_fetch:
            local_file = file_pattern.replace('{exp_name}', job_name)
            remote_file = file_pattern.replace('{exp_name}', job_name)
            self.ssh.run(f"scp {self.ssh.username}@{self.ssh.hostname}:{self.remote_dir}/{remote_file} .")
        
        # Remove finished marker
        self.ssh.run(f"cd {self.remote_dir} && rm {job_name}.finished")