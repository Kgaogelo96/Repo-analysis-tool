"""One-pass aggregation of a parsed history into filterable metric tables.

The aggregate is built once per repository (cached against the history head)
so that metric queries with arbitrary filter combinations never re-scan the
raw commit list.
"""
import threading
from dataclasses import dataclass, field

from app.git_engine import author_merge
from app.git_engine.log_parser import ParsedHistory
from app.git_engine.mailmap import Identity


@dataclass(frozen=True, slots=True)
class Entry:
    """One (commit, file) change with the author identity already resolved."""

    commit_hash: str
    author_ts: int
    committer_ts: int
    author: Identity  # canonical (mailmap + manual-merge resolved)
    raw_name: str
    raw_email: str
    path: str
    added: int | None  # None for binary files
    removed: int | None  # None for binary files
    binary: bool

    @property
    def churn(self) -> int:
        if self.added is None or self.removed is None:
            return 0
        return self.added + self.removed


@dataclass(frozen=True, slots=True)
class CommitSummary:
    """Commit-level totals for one non-merge commit."""

    hash: str
    author_ts: int
    committer_ts: int
    author: Identity
    raw_name: str
    raw_email: str
    files: int
    binary_files: int
    added: int
    removed: int

    @property
    def churn(self) -> int:
        return self.added + self.removed


@dataclass(slots=True)
class HistoryAggregate:
    """Queryable aggregation of one repository's non-merge history."""

    repo_path: str
    head: str | None
    commits: list[CommitSummary]  # newest first (parser order)
    entries: list[Entry]  # commit order, then change order
    entries_by_hash: dict[str, list[Entry]]
    authors: list[Identity]  # unique canonical identities, first-seen order


@dataclass(frozen=True, slots=True)
class Filters:
    """Commit-set selection, mirroring the /commits endpoint semantics."""

    since: int | None = None  # inclusive, committer timestamp
    until: int | None = None  # exclusive, committer timestamp
    author: str | None = None  # case-insensitive substring, canonical or raw
    path: str | None = None  # exact file path or directory prefix
    hashes: frozenset[str] | None = None  # full-or-short hash whitelist
    from_index: int | None = None  # 0-based position in the newest-first log (inclusive)
    to_index: int | None = None  # exclusive end position of the log slice


@dataclass(slots=True)
class Selection:
    """A filtered commit set with its file-level entries."""

    commits: list[CommitSummary]  # passed the commit-level filters
    entries: list[Entry]  # also passed the path filter
    path: str | None  # the path filter, if any (drives commit counting)


def build_aggregate(
    history: ParsedHistory,
    manual_merges: dict[tuple[str, str], Identity] | None = None,
) -> HistoryAggregate:
    """Aggregate a parsed history in a single pass.

    Identity resolution and path strings are memoized so mailmap/manual-merge
    rules run once per distinct raw author and repeated file paths stay shared.
    """
    manual_merges = manual_merges or {}
    identities: dict[tuple[str, str], Identity] = {}
    paths: dict[str, str] = {}
    commits: list[CommitSummary] = []
    entries: list[Entry] = []
    entries_by_hash: dict[str, list[Entry]] = {}
    authors: list[Identity] = []
    seen: set[Identity] = set()

    for commit in history.commits:
        key = (commit.author_name, commit.author_email)
        author = identities.get(key)
        if author is None:
            canonical = history.author_identity(commit)
            author = identities[key] = author_merge.resolve_author(
                manual_merges, commit.author_name, commit.author_email, canonical
            )
            if author not in seen:
                seen.add(author)
                authors.append(author)
        commits.append(
            CommitSummary(
                hash=commit.hash,
                author_ts=commit.author_ts,
                committer_ts=commit.committer_ts,
                author=author,
                raw_name=commit.author_name,
                raw_email=commit.author_email,
                files=len(commit.changes),
                binary_files=sum(1 for change in commit.changes if change.binary),
                added=commit.added,
                removed=commit.removed,
            )
        )
        commit_entries: list[Entry] = []
        for change in commit.changes:
            entry = Entry(
                commit_hash=commit.hash,
                author_ts=commit.author_ts,
                committer_ts=commit.committer_ts,
                author=author,
                raw_name=commit.author_name,
                raw_email=commit.author_email,
                path=paths.setdefault(change.path, change.path),
                added=change.added,
                removed=change.removed,
                binary=change.binary,
            )
            entries.append(entry)
            commit_entries.append(entry)
        entries_by_hash[commit.hash] = commit_entries

    return HistoryAggregate(
        repo_path=history.repo_path,
        head=history.head,
        commits=commits,
        entries=entries,
        entries_by_hash=entries_by_hash,
        authors=authors,
    )


def select(aggregate: HistoryAggregate, filters: Filters) -> Selection:
    """Apply the shared filter semantics to an aggregate.

    The commit-set selector follows the dashboard contract's precedence:
    explicit hashes win over a newest-first log-slice interval, which wins
    over a time window. `author` narrows whichever set remains, and the path
    filter additionally narrows which of a commit's entries count.
    """
    author_query = filters.author.strip().lower() if filters.author else None
    prefix = filters.path.rstrip("/") + "/" if filters.path else None
    hashes = filters.hashes or None

    allowed: set[str] | None = None  # when set, only these commit hashes survive
    window = False
    if hashes is not None:
        allowed = {
            summary.hash
            for summary in aggregate.commits
            if any(summary.hash.startswith(h) for h in hashes)
        }
    elif filters.from_index is not None or filters.to_index is not None:
        total = len(aggregate.commits)
        start = max(0, filters.from_index or 0)
        end = total if filters.to_index is None else min(max(filters.to_index, start), total)
        allowed = {summary.hash for summary in aggregate.commits[start:end]}
    else:
        window = True

    commits: list[CommitSummary] = []
    entries: list[Entry] = []
    for summary in aggregate.commits:
        if allowed is not None:
            if summary.hash not in allowed:
                continue
        elif window:
            if filters.since is not None and summary.committer_ts < filters.since:
                continue
            if filters.until is not None and summary.committer_ts >= filters.until:
                continue
        if author_query is not None:
            haystack = (
                summary.author.name.lower(),
                summary.author.email.lower(),
                summary.raw_name.lower(),
                summary.raw_email.lower(),
            )
            if not any(author_query in value for value in haystack):
                continue
        commits.append(summary)
        commit_entries = aggregate.entries_by_hash.get(summary.hash, ())
        if filters.path is None:
            entries.extend(commit_entries)
        else:
            entries.extend(
                entry
                for entry in commit_entries
                if entry.path == filters.path or entry.path.startswith(prefix)
            )
    return Selection(commits=commits, entries=entries, path=filters.path)


def counted_commits(selection: Selection) -> list[CommitSummary]:
    """Commits credited in set totals: all selected, or only those with matching files.

    Without a path filter every selected commit counts (including empty ones);
    with one, only commits that have at least one matching entry do — mirroring
    the /commits endpoint's visibility rule.
    """
    if selection.path is None:
        return selection.commits
    hashes = {entry.commit_hash for entry in selection.entries}
    return [commit for commit in selection.commits if commit.hash in hashes]


# --- process-wide cache -------------------------------------------------------------

_guard = threading.Lock()
_cache: dict[str, tuple[str | None, HistoryAggregate]] = {}


def get_or_build(repo_id: str, history: ParsedHistory) -> HistoryAggregate:
    """Return the cached aggregate for a repo, rebuilding when absent or stale."""
    with _guard:
        cached = _cache.get(repo_id)
        if cached is not None and cached[0] == history.head:
            return cached[1]
        aggregate = build_aggregate(history, author_merge.resolver(repo_id))
        _cache[repo_id] = (history.head, aggregate)
        return aggregate


def invalidate(repo_id: str) -> None:
    """Drop the cached aggregate (used when a repository is deleted)."""
    with _guard:
        _cache.pop(repo_id, None)
