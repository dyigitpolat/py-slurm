"""slurmster.core (legacy)

This module has been **refactored** into smaller, focused sub-modules for
maintainability:

- env_setup.py    configuration loading + remote environment preparation
- submission.py   job script generation & sbatch submission
- monitor.py      live log streaming for a single run
- run_status.py   status table helpers
- fetch.py        retrieve finished run directories
- cancel.py       cancel running jobs
- remote_utils.py  shared helper utilities (path resolution, wait helpers, …)

The public API remains unchanged.  All former symbols are re-exported from the
new implementation modules so existing imports keep working unchanged.
"""

from .env_setup import load_config, setup_remote_env  # noqa: F401
from .remote_utils import wait_for_job  # noqa: F401
from .submission import submit_all  # noqa: F401
from .monitor import monitor  # noqa: F401
from .run_status import status  # noqa: F401
from .fetch import fetch  # noqa: F401
# re-export cancellation helpers
from .cancel import cancel, cancel_all  # noqa: F401

__all__ = [
    "load_config",
    "setup_remote_env",
    "wait_for_job",
    "submit_all",
    "monitor",
    "status",
    "fetch",
    "cancel",
    "cancel_all",
]
