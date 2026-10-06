"""Metric query endpoints driving the dashboard (tree, files, charts, authors)."""
from fastapi import APIRouter, HTTPException

from app import data_store, state
from app.metrics import aggregator, author_metrics, dir_metrics, file_metrics

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

FILES_LIMIT_DEFAULT = 200
FILES_LIMIT_MAX = 1000
_SORT_KEYS = {"churn", "added", "removed", "commits", "path"}


def _safe_text(value: str) -> str:
    """Re-encode surrogate-escaped text (e.g. invalid-UTF-8 paths) as valid UTF-8.

    The log parser round-trips undecodable bytes with `surrogateescape`; such
    strings crash JSON serialization, so they are repaired at the API boundary
    by restoring the raw bytes and re-decoding with U+FFFD replacements.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    return value


def _load(repo_id: str) -> aggregator.HistoryAggregate:
    """Aggregate for a repository; 404 when unknown, 409 when not ready."""
    record = state.registry().get(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown repository id: {repo_id}")
    if record.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"repository is not ready yet (status: {record.status}, stage: {record.stage})",
        )
    history = data_store.get_or_parse(repo_id, record.path)
    return aggregator.get_or_build(repo_id, history)


def _hash_set(raw: str | None) -> frozenset[str] | None:
    """Comma-separated full-or-short hashes; empty input disables the filter."""
    if not raw:
        return None
    tokens = frozenset(token.strip().lower() for token in raw.split(",") if token.strip())
    return tokens or None


def _select(
    repo_id: str,
    since: int | None,
    until: int | None,
    author: str | None,
    path: str | None,
    hashes: str | None,
    from_index: int | None = None,
    to_index: int | None = None,
) -> aggregator.Selection:
    aggregate = _load(repo_id)
    filters = aggregator.Filters(
        since=since,
        until=until,
        author=author,
        path=path,
        hashes=_hash_set(hashes),
        from_index=from_index,
        to_index=to_index,
    )
    return aggregator.select(aggregate, filters)


def _file_row(stat: file_metrics.FileStat, commit_count: int) -> dict:
    modifications = len(stat.modifying)
    return {
        "path": _safe_text(stat.path),
        "added": stat.added,
        "removed": stat.removed,
        "growth": stat.growth,
        "churn": stat.churn,
        "modifications": modifications,
        "frequency": round(modifications / commit_count, 4) if commit_count else 0.0,
        "churn_rate": round(stat.churn / commit_count, 4) if commit_count else 0.0,
        "commits": len(stat.commits),
        "binary_commits": len(stat.binary_commits),
        "authors": len(stat.authors),
        "last_ts": stat.last_ts,
    }


def _sanitize_tree(node: dict) -> dict:
    """Repair surrogate-escaped names/paths through a serialized tree in place."""
    node["name"] = _safe_text(node["name"])
    node["path"] = _safe_text(node["path"])
    for child in node.get("children", ()):
        _sanitize_tree(child)
    return node


def _sort_value(stat: file_metrics.FileStat, key: str):
    if key == "path":
        return stat.path.lower()
    if key == "commits":
        return len(stat.commits)
    return getattr(stat, key)


# --- endpoints ----------------------------------------------------------------------


@router.get("/{repo_id}/summary")
def repo_summary(
    repo_id: str,
    since: int | None = None,
    until: int | None = None,
    author: str | None = None,
    path: str | None = None,
    hashes: str | None = None,
    from_index: int | None = None,
    to_index: int | None = None,
) -> dict:
    """Totals and rates for the selected commit set."""
    selection = _select(repo_id, since, until, author, path, hashes, from_index, to_index)
    return dir_metrics.commit_set_totals(selection)


@router.get("/{repo_id}/authors")
def authors(
    repo_id: str,
    since: int | None = None,
    until: int | None = None,
    author: str | None = None,
    path: str | None = None,
    hashes: str | None = None,
    from_index: int | None = None,
    to_index: int | None = None,
) -> dict:
    """Per-canonical-author churn, modifications and ownership (churn-descending)."""
    selection = _select(repo_id, since, until, author, path, hashes, from_index, to_index)
    ownership_selection = _select(repo_id, since, until, None, path, hashes, from_index, to_index)
    ownership_total = sum((entry.added or 0) + (entry.removed or 0) for entry in ownership_selection.entries)
    stats = author_metrics.author_stats(selection, ownership_total)
    return {
        "total": len(stats),
        "authors": [
            {
                "name": _safe_text(stat.author.name),
                "email": _safe_text(stat.author.email),
                "raw": [
                    {"name": _safe_text(raw_name), "email": _safe_text(raw_email)}
                    for raw_name, raw_email in stat.raw
                ],
                "commits": len(stat.commits),
                "files": len(stat.files),
                "added": stat.added,
                "removed": stat.removed,
                "churn": stat.churn,
                "growth": stat.growth,
                "modifications": len(stat.modifying),
                "first_ts": stat.first_ts,
                "last_ts": stat.last_ts,
                "ownership": round(stat.ownership, 4),
            }
            for stat in stats
        ],
    }


@router.get("/{repo_id}/authors/identities")
def author_identities(repo_id: str) -> dict:
    """Raw (name, email) identities with their canonical mapping, for merge tooling."""
    aggregate = _load(repo_id)
    counts: dict[tuple[str, str], list] = {}
    for summary in aggregate.commits:
        key = (summary.raw_name, summary.raw_email)
        item = counts.get(key)
        if item is None:
            item = counts[key] = [summary.author, 0]
        item[1] += 1
    ranked = sorted(
        counts.items(),
        key=lambda kv: (-kv[1][1], kv[0][0].lower(), kv[0][1].lower()),
    )
    return {
        "total": len(ranked),
        "identities": [
            {
                "raw_name": _safe_text(raw_name),
                "raw_email": _safe_text(raw_email),
                "author": {
                    "name": _safe_text(canonical.name),
                    "email": _safe_text(canonical.email),
                },
                "commits": count,
            }
            for (raw_name, raw_email), (canonical, count) in ranked
        ],
    }


@router.get("/{repo_id}/files")
def files(
    repo_id: str,
    since: int | None = None,
    until: int | None = None,
    author: str | None = None,
    path: str | None = None,
    hashes: str | None = None,
    from_index: int | None = None,
    to_index: int | None = None,
    sort: str = "churn",
    order: str = "desc",
    offset: int = 0,
    limit: int = FILES_LIMIT_DEFAULT,
) -> dict:
    """Flat per-file rows, sortable and paginated."""
    selection = _select(repo_id, since, until, author, path, hashes, from_index, to_index)
    stats = list(file_metrics.file_stats(selection).values())
    key = sort if sort in _SORT_KEYS else "churn"
    stats.sort(key=lambda stat: _sort_value(stat, key), reverse=order.lower() != "asc")
    offset = max(0, offset)
    limit = max(1, min(limit, FILES_LIMIT_MAX))
    window = stats[offset : offset + limit]
    commit_count = len(selection.commits)
    return {
        "total": len(stats),
        "offset": offset,
        "limit": limit,
        "files": [_file_row(stat, commit_count) for stat in window],
    }


@router.get("/{repo_id}/tree")
def tree(
    repo_id: str,
    since: int | None = None,
    until: int | None = None,
    author: str | None = None,
    path: str | None = None,
    hashes: str | None = None,
    from_index: int | None = None,
    to_index: int | None = None,
) -> dict:
    """Nested directory rollup (dirs first, then files).

    `path` both narrows the selection and re-roots the returned node on that
    directory, so the dashboard can drill into any subtree lazily.
    """
    selection = _select(repo_id, since, until, author, path, hashes, from_index, to_index)
    stats = file_metrics.file_stats(selection)
    commit_count = len(selection.commits)
    root = dir_metrics.directory_rollup(stats, commit_count)
    if path:
        root = dir_metrics.find_node(root, path) or dir_metrics.empty_node(path)
    return _sanitize_tree(root)


@router.get("/{repo_id}/series")
def series(
    repo_id: str,
    bucket: str = "month",
    since: int | None = None,
    until: int | None = None,
    author: str | None = None,
    path: str | None = None,
    hashes: str | None = None,
    from_index: int | None = None,
    to_index: int | None = None,
) -> dict:
    """Bucketed churn/growth time series for the selected commit set."""
    selection = _select(repo_id, since, until, author, path, hashes, from_index, to_index)
    return dir_metrics.timeseries(selection, bucket)
