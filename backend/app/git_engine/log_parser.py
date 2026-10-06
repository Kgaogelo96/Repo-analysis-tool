"""Parses `git log --no-merges -M50% --numstat` output into structured commit records."""
from dataclasses import dataclass, field
from pathlib import Path

from app.git_engine.mailmap import Identity, Mailmap, load_mailmap
from app.git_engine.runner import run_git

# Marker prefixed to every commit header so headers can be located in the stream.
_MARKER = b"RATCOMMIT"
_LOG_FORMAT = "RATCOMMIT%x00%H%x00%an%x00%ae%x00%at%x00%cn%x00%ce%x00%ct"
_HEADER_FIELDS = 7  # hash, author name/email/ts, committer name/email/ts
PARSE_TIMEOUT_SECONDS = 600


class GitParseError(RuntimeError):
    """Raised when a repository's history cannot be parsed."""


@dataclass(slots=True)
class Change:
    """One file touched by a commit (renames carry the new path only)."""

    path: str
    added: int | None  # None for binary files (git reports "-")
    removed: int | None  # None for binary files (git reports "-")
    binary: bool = False

    @property
    def churn(self) -> int:
        if self.added is None or self.removed is None:
            return 0
        return self.added + self.removed


@dataclass(slots=True)
class Commit:
    """A non-merge commit with its file-level changes."""

    hash: str
    author_name: str
    author_email: str
    author_ts: int
    committer_name: str
    committer_email: str
    committer_ts: int
    changes: list[Change] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(change.added or 0 for change in self.changes)

    @property
    def removed(self) -> int:
        return sum(change.removed or 0 for change in self.changes)

    @property
    def churn(self) -> int:
        return self.added + self.removed


@dataclass(slots=True)
class ParsedHistory:
    """Full parsed history of one repository at a point in time."""

    repo_path: str
    ref: str
    head: str | None
    commits: list[Commit]
    mailmap: Mailmap
    _by_hash: dict[str, Commit] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_hash = {commit.hash: commit for commit in self.commits}

    @property
    def by_hash(self) -> dict[str, Commit]:
        return self._by_hash

    def author_identity(self, commit: Commit) -> Identity:
        """Canonical author of a commit after mailmap resolution."""
        return self.mailmap.resolve(commit.author_name, commit.author_email)


def parse_history(repo_path: Path | str, ref: str = "HEAD") -> ParsedHistory:
    """Parse the full non-merge history reachable from `ref` (one git invocation)."""
    repo_path = Path(repo_path)
    head = _resolve_ref(repo_path, ref)
    if head is None:
        raise GitParseError(f"cannot resolve ref {ref!r} in {repo_path}")
    proc = run_git(
        ["log", "--no-merges", "-M50%", "--numstat", "-z", f"--format={_LOG_FORMAT}", ref],
        cwd=repo_path,
        timeout=PARSE_TIMEOUT_SECONDS,
        check=False,
        text=False,
    )
    if proc.returncode != 0:
        message = _decode(proc.stderr).strip() or f"git log failed in {repo_path}"
        raise GitParseError(message)
    return ParsedHistory(
        repo_path=str(repo_path),
        ref=ref,
        head=head,
        commits=_parse_log(proc.stdout),
        mailmap=load_mailmap(repo_path, ref),
    )


def _resolve_ref(repo_path: Path, ref: str) -> str | None:
    proc = run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo_path, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _parse_log(raw: bytes) -> list[Commit]:
    """Walk the NUL-separated token stream produced by `git log -z --numstat`.

    Layout (verified against git 2.43): each commit is emitted as
    `RATCOMMIT\\0<hash>\\0<an>\\0<ae>\\0<at>\\0<cn>\\0<ce>\\0<ct>\\0`, followed by
    NUL-terminated numstat entries; the first entry of each commit carries a
    leading `\\n`. Regular entries are `<added>\\t<removed>\\t<path>` (the split
    is capped at 2 tabs so paths containing tabs survive); binary files report
    `-\\t-`; a rename leaves the path empty and appends two more tokens
    `<old>\\0<new>\\0` - the change is attributed to `<new>` (the rename's
    continuation tokens are consumed verbatim, never re-examined, because paths
    may legitimately start with a newline).
    """
    tokens = raw.split(b"\x00")
    commits: list[Commit] = []
    current: Commit | None = None
    index = 0
    total = len(tokens)
    while index < total:
        token = tokens[index]
        if token.strip(b"\n") == _MARKER:
            fields = tokens[index + 1 : index + 1 + _HEADER_FIELDS]
            if len(fields) < _HEADER_FIELDS:
                break  # truncated stream; keep what was parsed so far
            current = Commit(
                hash=_decode(fields[0]),
                author_name=_decode(fields[1]),
                author_email=_decode(fields[2]),
                author_ts=_to_int(fields[3]),
                committer_name=_decode(fields[4]),
                committer_email=_decode(fields[5]),
                committer_ts=_to_int(fields[6]),
            )
            commits.append(current)
            index += 1 + _HEADER_FIELDS
            continue
        if current is not None and b"\t" in token:
            parts = token.lstrip(b"\n").split(b"\t", 2)
            if len(parts) == 3:
                added_raw, removed_raw, path_raw = parts
                if path_raw == b"" and index + 2 < total:
                    # rename: the two following tokens are <old> and <new>
                    current.changes.append(
                        _make_change(added_raw, removed_raw, tokens[index + 2])
                    )
                    index += 3
                    continue
                if path_raw != b"":
                    current.changes.append(_make_change(added_raw, removed_raw, path_raw))
                    index += 1
                    continue
        index += 1
    return commits


def _make_change(added_raw: bytes, removed_raw: bytes, path_raw: bytes) -> Change:
    if added_raw == b"-" or removed_raw == b"-":
        return Change(path=_decode(path_raw), added=None, removed=None, binary=True)
    return Change(
        path=_decode(path_raw), added=_to_int(added_raw), removed=_to_int(removed_raw)
    )


def _decode(raw: bytes) -> str:
    """UTF-8 decode that round-trips invalid bytes instead of failing."""
    return raw.decode("utf-8", "surrogateescape")


def _to_int(raw: bytes) -> int:
    try:
        return int(raw.strip() or b"0")
    except ValueError:
        return 0
