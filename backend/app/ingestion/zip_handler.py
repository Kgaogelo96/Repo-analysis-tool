"""Zip archive ingestion: extract uploaded .zip archives and verify .git presence."""
import shutil
import zipfile
from pathlib import Path

IGNORED_TOP_LEVEL = {"__MACOSX"}


class ZipIngestionError(RuntimeError):
    """Raised when an uploaded archive cannot be ingested."""


def extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Extract `zip_path` into a fresh `dest_dir` and return the repository root.

    The returned path is the directory that directly contains `.git` (handles
    archives that wrap the repository in a single top-level folder).
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            _check_members(archive)
            archive.extractall(dest_dir)
    except zipfile.BadZipFile as exc:
        raise ZipIngestionError("the uploaded file is not a valid zip archive") from exc

    repo_root = find_repo_root(dest_dir)
    if repo_root is None:
        raise ZipIngestionError(
            "no .git file or directory found in the archive; "
            "upload a zip containing a full Git repository"
        )
    return repo_root


def find_repo_root(base: Path) -> Path | None:
    """Locate the directory holding `.git`: the root itself or a top-level child."""
    if (base / ".git").exists():
        return base
    for child in sorted(path for path in base.iterdir() if path.is_dir()):
        if child.name in IGNORED_TOP_LEVEL:
            continue
        if (child / ".git").exists():
            return child
    return None


def _check_members(archive: zipfile.ZipFile) -> None:
    """Reject absolute paths, drive letters and parent traversal (zip-slip)."""
    for member in archive.infolist():
        parts = Path(member.filename).parts
        if (
            member.filename.startswith(("/", "\\"))
            or ".." in parts
            or (parts and parts[0].endswith(":"))
        ):
            raise ZipIngestionError(f"archive contains an unsafe path: {member.filename!r}")
