import json
import os
from typing import Optional

def _sanitize(path):
    # keep alnum+-._ and strip others
    return "".join(ch for ch in path if ch.isalnum() or ch in "+-._")

class Registry:
    def __init__(self, user, host, remote_base_dir, local_root: Optional[str] = None):
        """Create (or load) a run registry.

        Parameters
        ----------
        user, host, remote_base_dir
            Identify the *remote* experiment location – together these make the key.
        local_root : str or None, optional
            Directory in which the hidden ``.slurmster`` workspace should live.
            If *None* (default), we fall back to ``~/.slurmster`` (previous
            behaviour).  Passing the directory that contains the YAML config file
            lets each experiment set live next to its configuration.
        """

        base_key = f"{user}@{host}:{remote_base_dir}"
        safe_base = _sanitize(base_key)

        if local_root is None:
            local_root = os.path.expanduser("~/.slurmster")

        self.root = os.path.join(os.path.abspath(local_root), safe_base)
        os.makedirs(self.root, exist_ok=True)
        self.results_dir = os.path.join(self.root, "results")
        os.makedirs(self.results_dir, exist_ok=True)
        self.path = os.path.join(self.root, "runs.json")
        self._data = {"runs": []}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def add_run(self, run):
        self._data["runs"].append(run)
        self._save()

    def update_run(self, exp_name=None, job_id=None, **fields):
        for r in self._data["runs"]:
            if (exp_name and r.get("exp_name") == exp_name) or (job_id and r.get("job_id") == job_id):
                r.update(fields)
        self._save()

    def find_run(self, exp_name=None, job_id=None):
        for r in self._data["runs"]:
            if (exp_name and r.get("exp_name") == exp_name) or (job_id and r.get("job_id") == job_id):
                return r
        return None

    def all_runs(self):
        return list(self._data.get("runs", []))

    def unfetched_runs(self):
        return [r for r in self.all_runs() if not r.get("fetched")]
