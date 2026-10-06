"""Runtime configuration: workspace paths and directory helpers."""
import os
import tempfile
from functools import lru_cache
from pathlib import Path

ENV_WORKSPACE = "RAT_WORKSPACE"


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".rat_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def workspace_dir() -> Path:
    """Resolve the workspace root.

    Order: $RAT_WORKSPACE -> <tmp>/rat_workspace -> <backend>/data/workspace.
    """
    candidates = []
    env = os.environ.get(ENV_WORKSPACE)
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path(tempfile.gettempdir()) / "rat_workspace")
    candidates.append(Path(__file__).resolve().parent.parent / "data" / "workspace")
    for candidate in candidates:
        if _is_writable(candidate):
            return candidate
    raise RuntimeError(
        "no writable workspace directory found; set the RAT_WORKSPACE environment variable"
    )


def repo_dir(repo_id: str) -> Path:
    """Working-tree location for an ingested repository."""
    return workspace_dir() / repo_id


@lru_cache(maxsize=1)
def uploads_dir() -> Path:
    """Scratch directory for raw uploaded archives."""
    directory = workspace_dir() / "_uploads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
