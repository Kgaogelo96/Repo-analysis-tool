"""Directory hierarchy rollups and commit-set metrics (totals, modifications, rates)."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.git_engine.mailmap import Identity
from app.metrics.aggregator import Selection, counted_commits
from app.metrics.file_metrics import FileStat

_DAY = 86400
BUCKET_SECONDS: dict[str, int | None] = {"day": _DAY, "week": 7 * _DAY, "month": None}


@dataclass(slots=True)
class _Node:
    """Mutable tree node accumulating the stats of everything beneath it."""

    name: str
    path: str
    is_file: bool
    added: int = 0
    removed: int = 0
    last_ts: int | None = None
    files: int = 0  # file leaves beneath a directory (1 for file nodes)
    commits: set[str] = field(default_factory=set)
    authors: set[Identity] = field(default_factory=set)
    binary_commits: set[str] = field(default_factory=set)
    modifying: set[str] = field(default_factory=set)  # commits that changed lines (λ > 0)
    children: dict[str, "_Node"] = field(default_factory=dict)


def directory_rollup(file_stats: dict[str, FileStat], commit_count: int) -> dict:
    """Nest per-file stats into a directory tree (parent totals = subtree sums).

    `commit_count` (|H|) is the denominator for the per-node frequency and
    churn-rate metrics; nodes are serialized in the dashboard's contract
    shape: {name, path, kind, has_children, metrics, children}.
    """
    root = _Node(name="", path="", is_file=False)
    for stat in file_stats.values():
        parts = stat.path.split("/")
        node = root
        _absorb(node, stat)
        node.files += 1
        for depth in range(len(parts) - 1):
            name = parts[depth]
            child = node.children.get(name)
            if child is None:
                child = _Node(name=name, path="/".join(parts[: depth + 1]), is_file=False)
                node.children[name] = child
            # a path reused as both file and directory across history folds into
            # the same node rather than losing either side's stats
            node = child
            _absorb(node, stat)
            node.files += 1
        leaf = _Node(name=parts[-1], path=stat.path, is_file=True)
        node.children[parts[-1]] = leaf
        _absorb(leaf, stat)
        leaf.files = 1
    return _serialize(root, commit_count)


def _absorb(node: _Node, stat: FileStat) -> None:
    node.added += stat.added
    node.removed += stat.removed
    node.commits.update(stat.commits)
    node.authors.update(stat.authors)
    node.binary_commits.update(stat.binary_commits)
    node.modifying.update(stat.modifying)
    if stat.last_ts is not None and (node.last_ts is None or stat.last_ts > node.last_ts):
        node.last_ts = stat.last_ts


def _serialize(node: _Node, denom: int) -> dict:
    """Contract shape for the dashboard tree: metrics nested per node."""
    added, removed = node.added, node.removed
    modifications = len(node.modifying)
    is_file = node.is_file
    payload = {
        "name": node.name,
        "path": node.path,
        "kind": "file" if is_file else "dir",
        "has_children": not is_file and bool(node.children),
        "metrics": {
            "files": 1 if is_file else node.files,
            "added": added,
            "removed": removed,
            "growth": added - removed,
            "churn": added + removed,
            "modifications": modifications,
            "frequency": round(modifications / denom, 4) if denom else 0.0,
            "churn_rate": round((added + removed) / denom, 4) if denom else 0.0,
            "authors": len(node.authors),
            "commits": len(node.commits),
            "binary_commits": len(node.binary_commits),
            "last_ts": node.last_ts,
        },
    }
    if not is_file:
        payload["children"] = [
            _serialize(child, denom)
            for child in sorted(node.children.values(), key=lambda c: (c.is_file, c.name.lower()))
        ]
    return payload


def find_node(node: dict, path: str) -> dict | None:
    """Serialized descendant whose path equals `path` (for tree re-rooting)."""
    if node["path"] == path:
        return node
    for child in node.get("children", ()):
        found = find_node(child, path)
        if found is not None:
            return found
    return None


def empty_node(path: str) -> dict:
    """Zeroed directory placeholder for a drilled path with no activity."""
    return {
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "kind": "dir",
        "has_children": False,
        "metrics": {
            "files": 0,
            "added": 0,
            "removed": 0,
            "growth": 0,
            "churn": 0,
            "modifications": 0,
            "frequency": 0.0,
            "churn_rate": 0.0,
            "authors": 0,
            "commits": 0,
            "binary_commits": 0,
            "last_ts": None,
        },
        "children": [],
    }


def commit_set_totals(selection: Selection) -> dict:
    """Totals and rates for the selected commit set (lines from matching entries)."""
    counted = counted_commits(selection)
    added = sum(entry.added or 0 for entry in selection.entries)
    removed = sum(entry.removed or 0 for entry in selection.entries)
    timestamps = [commit.committer_ts for commit in selection.commits]
    commit_count = len(selection.commits)
    churn = added + removed
    modifications = len(
        {
            entry.commit_hash
            for entry in selection.entries
            if (entry.added or 0) + (entry.removed or 0) > 0
        }
    )
    return {
        "commits": commit_count,
        "authors": len({commit.author for commit in counted}),
        "files": len({entry.path for entry in selection.entries}),
        "binary_files": len({entry.path for entry in selection.entries if entry.binary}),
        "added": added,
        "removed": removed,
        "churn": churn,
        "growth": added - removed,
        "modifications": modifications,
        "frequency": round(modifications / commit_count, 4) if commit_count else 0.0,
        "churn_rate": round(churn / commit_count, 4) if commit_count else 0.0,
        "first_ts": min(timestamps) if timestamps else None,
        "last_ts": max(timestamps) if timestamps else None,
        "avg_churn_per_commit": round(churn / commit_count, 2) if commit_count else 0.0,
    }


def timeseries(selection: Selection, bucket: str = "month") -> dict:
    """Bucket the selection's file activity into ascending time buckets (UTC)."""
    name = (bucket or "month").lower()
    if name not in BUCKET_SECONDS:
        name = "month"

    buckets: dict[int, dict] = {}
    for entry in selection.entries:
        start = _bucket_start(entry.committer_ts, name)
        point = buckets.get(start)
        if point is None:
            point = buckets[start] = {"commits": set(), "added": 0, "removed": 0}
        point["commits"].add(entry.commit_hash)
        point["added"] += entry.added or 0
        point["removed"] += entry.removed or 0

    points = []
    for start in sorted(buckets):
        raw = buckets[start]
        added, removed = raw["added"], raw["removed"]
        moment = datetime.fromtimestamp(start, tz=timezone.utc)
        key = f"{moment:%Y-%m}" if name == "month" else f"{moment:%Y-%m-%d}"
        points.append(
            {
                "key": key,
                "start_ts": start,
                "commits": len(raw["commits"]),
                "added": added,
                "removed": removed,
                "churn": added + removed,
                "growth": added - removed,
            }
        )
    return {"bucket": name, "bucket_seconds": BUCKET_SECONDS[name], "buckets": points}


def _bucket_start(ts: int, name: str) -> int:
    """Start timestamp of the UTC bucket containing `ts`."""
    if name == "month":
        moment = datetime.fromtimestamp(ts, tz=timezone.utc)
        return int(moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    if name == "day":
        return ts - ts % _DAY
    days = ts // _DAY
    return (days - (days + 3) % 7) * _DAY  # weeks start Monday; epoch day 0 was a Thursday
