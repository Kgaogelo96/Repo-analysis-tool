"""Remote repository ingestion: full clones of remote Git URLs."""
import re
from pathlib import Path

from app.git_engine.runner import GitError, run_git

CLONE_TIMEOUT_SECONDS = 30 * 60
_URL_PATTERN = re.compile(r"^(?:https?://|git://|ssh://|git@)[^\s]+$")


class CloneError(RuntimeError):
    """Raised when a remote repository cannot be reached or cloned."""


def validate_url(url: str) -> str:
    """Normalize and validate a remote URL; raise CloneError when unsupported."""
    cleaned = (url or "").strip()
    if not _URL_PATTERN.match(cleaned):
        raise CloneError(
            "unsupported repository URL: expected an http(s), git, ssh or scp-style address"
        )
    return cleaned


def clone_repo(url: str, dest_dir: Path) -> Path:
    """Clone the full history (all branches, no shallow truncation) into `dest_dir`."""
    dest_dir = Path(dest_dir)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_git(
            ["clone", "--no-hardlinks", "--quiet", url, str(dest_dir)],
            timeout=CLONE_TIMEOUT_SECONDS,
        )
    except GitError as exc:
        raise CloneError(_friendly_message(str(exc))) from exc
    return dest_dir


def _friendly_message(raw: str) -> str:
    """Map common git clone failures onto actionable messages for the UI."""
    lowered = raw.lower()
    if "could not resolve host" in lowered or "name or service not known" in lowered:
        return "could not reach the remote host (DNS resolution failed)"
    if "timed out" in lowered:
        return "the connection to the remote host timed out"
    if "repository not found" in lowered or "error: 404" in lowered or "not found" in lowered:
        return "repository not found at the given URL (check the address and access rights)"
    if (
        "authentication failed" in lowered
        or "could not read username" in lowered
        or "permission denied" in lowered
    ):
        return "authentication failed: the repository may be private or require credentials"
    return f"git clone failed: {raw}"
