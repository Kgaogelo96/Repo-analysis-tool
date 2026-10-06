"""Per-file metrics: added/removed lines, growth, churn."""
from dataclasses import dataclass, field

from app.git_engine.mailmap import Identity
from app.metrics.aggregator import Selection


@dataclass(slots=True)
class FileStat:
    """Aggregated line-level metrics for one file path."""

    path: str
    added: int = 0
    removed: int = 0
    last_ts: int | None = None  # newest committer timestamp touching the file
    commits: set[str] = field(default_factory=set)
    authors: set[Identity] = field(default_factory=set)
    binary_commits: set[str] = field(default_factory=set)
    modifying: set[str] = field(default_factory=set)  # commits that changed lines (λ > 0)

    @property
    def churn(self) -> int:
        return self.added + self.removed

    @property
    def growth(self) -> int:
        return self.added - self.removed


def file_stats(selection: Selection) -> dict[str, FileStat]:
    """Aggregate the selection's entries into per-file statistics."""
    stats: dict[str, FileStat] = {}
    for entry in selection.entries:
        stat = stats.get(entry.path)
        if stat is None:
            stat = stats[entry.path] = FileStat(path=entry.path)
        stat.commits.add(entry.commit_hash)
        stat.authors.add(entry.author)
        if entry.binary:
            stat.binary_commits.add(entry.commit_hash)
        else:
            stat.added += entry.added or 0
            stat.removed += entry.removed or 0
        if (entry.added or 0) + (entry.removed or 0) > 0:
            stat.modifying.add(entry.commit_hash)
        if stat.last_ts is None or entry.committer_ts > stat.last_ts:
            stat.last_ts = entry.committer_ts
    return stats
