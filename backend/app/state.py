"""In-memory registry of ingested repositories, persisted to the workspace."""
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app import config

REGISTRY_FILENAME = "registry.json"

# Statuses: queued -> processing (stages: extracting | cloning -> verifying -> parsing)
# -> ready | error


def new_repo_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class RepoRecord:
    id: str
    name: str
    source: str  # "zip" | "clone"
    origin: str  # original filename or remote URL
    path: str  # absolute path of the working tree that contains .git
    status: str = "processing"  # queued | processing | ready | error
    stage: str = ""  # human-readable progress detail while processing
    error: str | None = None
    head: str | None = None
    commit_count: int | None = None  # non-merge commits reachable from HEAD
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class RepoRegistry:
    """Thread-safe collection of RepoRecords, mirrored to registry.json."""

    def __init__(self, root: Path):
        self._lock = threading.RLock()
        self._file = Path(root) / REGISTRY_FILENAME
        self._repos: dict[str, RepoRecord] = {}
        self._load()

    def create(
        self,
        *,
        repo_id: str,
        name: str,
        source: str,
        origin: str,
        path: str,
        stage: str = "queued",
    ) -> RepoRecord:
        record = RepoRecord(
            id=repo_id, name=name, source=source, origin=origin, path=path, stage=stage
        )
        with self._lock:
            self._repos[record.id] = record
            self._save()
        return record

    def get(self, repo_id: str) -> RepoRecord | None:
        with self._lock:
            return self._repos.get(repo_id)

    def list(self) -> list[RepoRecord]:
        with self._lock:
            return sorted(self._repos.values(), key=lambda r: r.created_at, reverse=True)

    def update(self, repo_id: str, **fields: object) -> RepoRecord | None:
        with self._lock:
            record = self._repos.get(repo_id)
            if record is None:
                return None
            for key, value in fields.items():
                if not hasattr(record, key):
                    raise AttributeError(f"unknown RepoRecord field: {key}")
                setattr(record, key, value)
            self._save()
            return record

    def remove(self, repo_id: str) -> RepoRecord | None:
        with self._lock:
            record = self._repos.pop(repo_id, None)
            if record is not None:
                self._save()
            return record

    # --- persistence (best-effort; the workspace is ephemeral) ---

    def _load(self) -> None:
        try:
            payload = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        for item in payload.get("repos", []):
            try:
                record = RepoRecord(**item)
            except TypeError:
                continue
            if not Path(record.path).exists():
                continue  # workspace was wiped; drop stale entries
            if record.status in ("queued", "processing"):
                record.status = "error"
                record.stage = ""
                record.error = "ingestion was interrupted by a server restart"
            self._repos[record.id] = record

    def _save(self) -> None:
        tmp = self._file.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps({"repos": [r.to_dict() for r in self._repos.values()]}, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._file)
        except OSError:
            pass  # persistence is opportunistic; in-memory state remains authoritative


_registry_lock = threading.Lock()
_registry: RepoRegistry | None = None


def registry() -> RepoRegistry:
    """Lazily initialized process-wide registry."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = RepoRegistry(config.workspace_dir())
        return _registry
