"""Author metrics: modifications, churn and ownership per canonical author."""
from dataclasses import dataclass, field

from app.git_engine.mailmap import Identity
from app.metrics.aggregator import Selection, counted_commits


@dataclass(slots=True)
class AuthorStat:
    """Aggregated modifications and ownership for one canonical author."""

    author: Identity
    commits: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    added: int = 0
    removed: int = 0
    first_ts: int | None = None
    last_ts: int | None = None
    ownership: float = 0.0  # churn share of the selection, filled by author_stats()
    modifying: set[str] = field(default_factory=set)  # commits that changed lines (λ > 0)
    raw: tuple[tuple[str, str], ...] = ()  # raw identities folded here, filled by author_stats()

    @property
    def churn(self) -> int:
        return self.added + self.removed

    @property
    def growth(self) -> int:
        return self.added - self.removed


def author_stats(selection: Selection, ownership_total_churn: int | None = None) -> list[AuthorStat]:
    """Per-canonical-author statistics over the selection, churn-descending."""
    stats: dict[Identity, AuthorStat] = {}

    def stat_for(author: Identity) -> AuthorStat:
        stat = stats.get(author)
        if stat is None:
            stat = stats[author] = AuthorStat(author=author)
        return stat

    raws: dict[Identity, list[tuple[str, str]]] = {}
    for commit in counted_commits(selection):
        stat = stat_for(commit.author)
        stat.commits.add(commit.hash)
        pair = (commit.raw_name, commit.raw_email)
        folded = raws.setdefault(commit.author, [])
        if pair not in folded:
            folded.append(pair)
        if stat.first_ts is None or commit.committer_ts < stat.first_ts:
            stat.first_ts = commit.committer_ts
        if stat.last_ts is None or commit.committer_ts > stat.last_ts:
            stat.last_ts = commit.committer_ts
    for entry in selection.entries:
        stat = stat_for(entry.author)
        stat.files.add(entry.path)
        stat.added += entry.added or 0
        stat.removed += entry.removed or 0
        if (entry.added or 0) + (entry.removed or 0) > 0:
            stat.modifying.add(entry.commit_hash)

    total_churn = (
        ownership_total_churn
        if ownership_total_churn is not None
        else sum(stat.churn for stat in stats.values())
    )
    for stat in stats.values():
        stat.ownership = stat.churn / total_churn if total_churn else 0.0
        stat.raw = tuple(raws.get(stat.author, ()))
    return sorted(
        stats.values(),
        key=lambda stat: (-stat.churn, stat.author.name.lower(), stat.author.email.lower()),
    )
