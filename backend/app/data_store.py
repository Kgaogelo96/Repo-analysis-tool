"""Process-wide cache of parsed histories keyed by repository id.

Histories are parsed once during ingestion and stored here. The registry on
disk survives server restarts, so instead of eagerly re-parsing every
repository at startup the cache re-parses lazily on first access.
"""
import threading
from pathlib import Path

from app.git_engine.log_parser import ParsedHistory, parse_history

_guard = threading.Lock()
_histories: dict[str, ParsedHistory] = {}
_parse_locks: dict[str, threading.Lock] = {}


def _parse_lock(repo_id: str) -> threading.Lock:
    with _guard:
        lock = _parse_locks.get(repo_id)
        if lock is None:
            lock = _parse_locks[repo_id] = threading.Lock()
        return lock


def put(repo_id: str, history: ParsedHistory) -> None:
    with _guard:
        _histories[repo_id] = history


def get(repo_id: str) -> ParsedHistory | None:
    with _guard:
        return _histories.get(repo_id)


def invalidate(repo_id: str) -> None:
    """Drop the cached history (used when a repository is deleted)."""
    with _guard:
        _histories.pop(repo_id, None)
        _parse_locks.pop(repo_id, None)


def get_or_parse(repo_id: str, repo_path: Path | str) -> ParsedHistory:
    """Return the cached history, parsing on demand (lazy re-parse after restart)."""
    history = get(repo_id)
    if history is not None:
        return history
    with _parse_lock(repo_id):
        history = get(repo_id)
        if history is None:
            history = parse_history(repo_path)
            put(repo_id, history)
        return history
