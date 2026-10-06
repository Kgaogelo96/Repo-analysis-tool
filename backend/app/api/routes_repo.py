"""Repository lifecycle endpoints: ingestion (zip/URL), listing and deletion."""
import re
import shutil
import threading
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import config, state
from app.git_engine import runner
from app.ingestion import clone_handler, zip_handler

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
    state.registry().update(repo_id, status="ready", stage="", error=None, head=head)


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


@router.delete("/{repo_id}", status_code=204)
def delete_repo(repo_id: str) -> None:
    """Remove a repository from the registry and delete its workspace data."""
    record = _require(repo_id)
    state.registry().remove(repo_id)
    shutil.rmtree(record.path, ignore_errors=True)
    (config.uploads_dir() / f"{repo_id}.zip").unlink(missing_ok=True)
