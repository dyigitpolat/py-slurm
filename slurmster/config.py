from dataclasses import dataclass, field
from typing import List

@dataclass
class Config:
    """Minimal configuration container used by JobManager.

    Note: The richer YAML-based configuration workflow is implemented in
    `slurmster.core`.  This class only exists so that static type checkers
    (e.g. Pylance) can resolve the symbol when working with the legacy
    JobManager API.
    """

    # Grid parameters provided as strings like "lr:0.1,0.01".
    grid_params: List[str] = field(default_factory=list)

    # SBATCH directive templates (one per line), e.g.
    # ["#SBATCH --job-name={exp_name}", "#SBATCH --time=00:10:00"]
    sbatch_directives: List[str] = field(default_factory=list)

    # Command template that will be executed on the cluster node.  Placeholders
    # such as "{lr}" or "{exp_name}" will be substituted before execution.
    run_cmd: str = ""

    # Optional list of filename patterns to pull back after job completion.
    files_to_fetch: List[str] = field(default_factory=list) 