"""Repository lifecycle endpoints: ingestion (zip/URL), listing, commits and deletion."""
import re
import shutil
import threading
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import config, data_store, state
from app.git_engine import log_parser, runner
from app.ingestion import clone_handler, zip_handler
from app.metrics import aggregator

router = APIRouter(prefix="/api/repo", tags=["repo"])

CHUNK_SIZE = 1024 * 1024


class CloneRequest(BaseModel):
    url: str = Field(
        min_length=1,
        description="Remote repository URL (http(s), git, ssh or scp-style)",
    )


def _derive_name(origin: str) -> str:
    """Best-effort repository name from a filename or URL."""
    name = origin.rstrip("/").rsplit("/", 1)[-1]
    lowered = name.lower()
    for suffix in (".git", ".zip"):
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            break
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return sanitized or "repo"


def _require(repo_id: str) -> state.RepoRecord:
    record = state.registry().get(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown repository id: {repo_id}")
    return record


# --- background ingestion workers ---------------------------------------------------


def _finalize(repo_id: str, root: Path) -> None:
    head = runner.head_commit(root)
    if head is None:
        _fail(repo_id, "could not resolve HEAD: the repository appears to be empty or corrupted")
        return
    state.registry().update(repo_id, stage="parsing")
    history = log_parser.parse_history(root)
    data_store.put(repo_id, history)
    state.registry().update(
        repo_id,
        status="ready",
        stage="",
        error=None,
        head=head,
        commit_count=len(history.commits),
    )


def _fail(repo_id: str, message: str) -> None:
    state.registry().update(repo_id, status="error", stage="", error=message)


def _ingest_zip(repo_id: str, upload_path: Path, dest: Path) -> None:
    registry = state.registry()
    try:
        registry.update(repo_id, stage="extracting")
        root = zip_handler.extract_zip(upload_path, dest)
        registry.update(repo_id, stage="verifying", path=str(root))
        _finalize(repo_id, root)
    except Exception as exc:  # keep worker failures visible in the registry
        shutil.rmtree(dest, ignore_errors=True)
        _fail(repo_id, str(exc))
    finally:
        upload_path.unlink(missing_ok=True)


def _ingest_clone(repo_id: str, url: str, dest: Path) -> None:
    registry = state.registry()
    try:
        registry.update(repo_id, stage="cloning")
        root = clone_handler.clone_repo(url, dest)
        registry.update(repo_id, stage="verifying", path=str(root))
        _finalize(repo_id, root)
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        _fail(repo_id, str(exc))


# --- endpoints ----------------------------------------------------------------------


@router.post("/upload", status_code=202)
async def upload_repo(file: UploadFile = File(...)) -> dict:
    """Ingest a repository from an uploaded .zip archive containing a full .git structure."""
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="expected a .zip archive")

    repo_id = state.new_repo_id()
    upload_path = config.uploads_dir() / f"{repo_id}.zip"
    first_chunk = await file.read(CHUNK_SIZE)
    if not first_chunk.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="the uploaded file is not a valid zip archive")
    with upload_path.open("wb") as out:
        out.write(first_chunk)
        while chunk := await file.read(CHUNK_SIZE):
            out.write(chunk)

    dest = config.repo_dir(repo_id)
    record = state.registry().create(
        repo_id=repo_id,
        name=_derive_name(filename),
        source="zip",
        origin=filename,
        path=str(dest),
        stage="queued",
    )
    threading.Thread(target=_ingest_zip, args=(repo_id, upload_path, dest), daemon=True).start()
    return record.to_dict()


@router.post("/clone", status_code=202)
def clone_repo(payload: CloneRequest) -> dict:
    """Ingest a repository by cloning a remote URL (full history, non-shallow)."""
    try:
        url = clone_handler.validate_url(payload.url)
    except clone_handler.CloneError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo_id = state.new_repo_id()
    dest = config.repo_dir(repo_id)
    record = state.registry().create(
        repo_id=repo_id,
        name=_derive_name(url),
        source="clone",
        origin=url,
        path=str(dest),
        stage="queued",
    )
    threading.Thread(target=_ingest_clone, args=(repo_id, url, dest), daemon=True).start()
    return record.to_dict()


@router.get("/list")
def list_repos() -> dict:
    """All ingested repositories with their ingestion status (newest first)."""
    return {"repos": [record.to_dict() for record in state.registry().list()]}


@router.get("/{repo_id}")
def get_repo(repo_id: str) -> dict:
    """Status and metadata for a single repository."""
    return _require(repo_id).to_dict()


@router.get("/{repo_id}/commits")
def list_commits(
    repo_id: str,
    offset: int = 0,
    limit: int = 200,
    since: int | None = None,
    until: int | None = None,
    author: str | None = None,
    path: str | None = None,
) -> dict:
    """Parsed non-merge commits (newest first), with optional filters.

    `since` is inclusive and `until` exclusive, both on author timestamps.
    `author` is a case-insensitive substring matched against the canonical and
    raw name/email; `path` matches a file exactly or a directory prefix.
    """
    record = _require(repo_id)
    if record.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"repository is not ready yet (status: {record.status}, stage: {record.stage})",
        )
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    history = data_store.get_or_parse(repo_id, record.path)

    author_query = author.strip().lower() if author else None
    path_prefix = path.rstrip("/") + "/" if path else None

    selected = []
    for commit in history.commits:
        if since is not None and commit.author_ts < since:
            continue
        if until is not None and commit.author_ts >= until:
            continue
        identity = history.author_identity(commit)
        if author_query:
            haystack = (
                identity.name.lower(),
                identity.email.lower(),
                commit.author_name.lower(),
                commit.author_email.lower(),
            )
            if not any(author_query in value for value in haystack):
                continue
        if path and not any(
            change.path == path
            or (path_prefix is not None and change.path.startswith(path_prefix))
            for change in commit.changes
        ):
            continue
        selected.append((commit, identity))

    window = selected[offset : offset + limit]
    return {
        "total": len(selected),
        "offset": offset,
        "limit": limit,
        "commits": [
            {
                "hash": commit.hash,
                "author_ts": commit.author_ts,
                "committer_ts": commit.committer_ts,
                "author": {"name": identity.name, "email": identity.email},
                "raw_author": {"name": commit.author_name, "email": commit.author_email},
                "files_changed": len(commit.changes),
                "binary_files": sum(1 for change in commit.changes if change.binary),
                "added": commit.added,
                "removed": commit.removed,
                "churn": commit.churn,
            }
            for commit, identity in window
        ],
    }


@router.delete("/{repo_id}", status_code=204)
def delete_repo(repo_id: str) -> None:
    """Remove a repository from the registry and delete its workspace data."""
    record = _require(repo_id)
    state.registry().remove(repo_id)
    data_store.invalidate(repo_id)
    shutil.rmtree(record.path, ignore_errors=True)
    (config.uploads_dir() / f"{repo_id}.zip").unlink(missing_ok=True)
