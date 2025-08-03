import importlib
import sys

# Import the original package
_orig = importlib.import_module("py_slurm")

# Re-export all public attributes
globals().update(_orig.__dict__)

# Ensure submodules are available under the slurmster.* namespace
_submods = [
    "cancel",
    "cli",
    "config",
    "connection",
    "core",
    "env_setup",
    "fetch",
    "job_manager",
    "monitor",
    "registry",
    "remote_utils",
    "run_status",
    "submission",
    "utils",
]
for _name in _submods:
    try:
        _module = importlib.import_module(f"py_slurm.{_name}")
        sys.modules[f"{__name__}.{_name}"] = _module
    except ModuleNotFoundError:
        # Skip if the submodule does not exist
        pass

# Maintain __all__ if defined in the original package
__all__ = getattr(_orig, "__all__", []) 