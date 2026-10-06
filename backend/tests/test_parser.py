"""Parser and mailmap tests against synthetic repositories with known git ground truth."""
import os
import subprocess
from pathlib import Path

import pytest

from app.git_engine import log_parser
from app.git_engine.mailmap import Identity, Mailmap

# Fixed identities/dates keep commit timestamps deterministic across runs. Both
# author and committer dates must be overridden per commit: git orders history
# by commit (committer) date, so equal dates would make output order unstable.
_BASE_ENV = {
    "GIT_AUTHOR_NAME": "Alice",
    "GIT_AUTHOR_EMAIL": "alice@example.com",
    "GIT_AUTHOR_DATE": "@1704100000 +0000",
    "GIT_COMMITTER_NAME": "Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.com",
    "GIT_COMMITTER_DATE": "@1704100000 +0000",
}


def _git(repo: Path, *args: str, **env_overrides: str) -> str:
    env = os.environ.copy()
    env.update(_BASE_ENV)
    env.update(env_overrides)
    proc = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)
    return proc.stdout.decode("utf-8", "replace")


def _init_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet", "--initial-branch=main")
    return repo


def _changes(commit: log_parser.Commit) -> list[tuple[str, int | None, int | None, bool]]:
    return [(c.path, c.added, c.removed, c.binary) for c in commit.changes]


@pytest.fixture()
def history_repo(tmp_path: Path) -> Path:
    """Five non-merge commits plus a merge that must be excluded from parsing."""
    repo = _init_repo(tmp_path)
    (repo / "sub").mkdir()

    (repo / "a.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (repo / "sub" / "b.txt").write_text("one\ntwo\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "c1")

    (repo / "a.txt").write_text("alpha\nbeta2\ndelta2\ngamma\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "--quiet",
        "-m",
        "c2",
        GIT_AUTHOR_NAME="Bob",
        GIT_AUTHOR_EMAIL="bob@example.com",
        GIT_AUTHOR_DATE="@1704101000 +0000",
        GIT_COMMITTER_DATE="@1704101000 +0000",
    )

    _git(repo, "mv", "a.txt", "renamed.txt")
    (repo / "renamed.txt").write_text("alpha\nbeta2\ndelta2\ngamma\nepsilon\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "--quiet",
        "-m",
        "c3",
        GIT_AUTHOR_DATE="@1704102000 +0000",
        GIT_COMMITTER_DATE="@1704102000 +0000",
    )

    (repo / "bin.dat").write_bytes(b"\x00\x01\x02\x03")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "--quiet",
        "-m",
        "c4",
        GIT_AUTHOR_NAME="Carol",
        GIT_AUTHOR_EMAIL="carol@example.com",
        GIT_AUTHOR_DATE="@1704103000 +0000",
        GIT_COMMITTER_DATE="@1704103000 +0000",
    )

    _git(repo, "checkout", "--quiet", "-b", "feature")
    (repo / "sub" / "b.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "--quiet",
        "-m",
        "b1",
        GIT_AUTHOR_NAME="Dave",
        GIT_AUTHOR_EMAIL="dave@example.com",
        GIT_AUTHOR_DATE="@1704104000 +0000",
        GIT_COMMITTER_DATE="@1704104000 +0000",
    )
    _git(repo, "checkout", "--quiet", "main")
    _git(
        repo,
        "merge",
        "--quiet",
        "--no-ff",
        "-m",
        "merge feature",
        "feature",
        GIT_AUTHOR_DATE="@1704105000 +0000",
        GIT_COMMITTER_DATE="@1704105000 +0000",
    )
    return repo


def test_history_matches_git(history_repo: Path) -> None:
    history = log_parser.parse_history(history_repo)

    expected_hashes = _git(history_repo, "rev-list", "--no-merges", "HEAD").split()
    parsed_hashes = [commit.hash for commit in history.commits]
    assert parsed_hashes == expected_hashes
    assert len(history.commits) == 5
    # `head` is the resolved ref (the merge commit here), not the newest non-merge
    head_hash = _git(history_repo, "rev-parse", "HEAD").strip()
    assert history.head == head_hash
    assert head_hash not in history.by_hash
    assert history.by_hash[expected_hashes[-1]].author_name == "Alice"


def test_change_details_and_totals(history_repo: Path) -> None:
    history = log_parser.parse_history(history_repo)
    b1, c4, c3, c2, c1 = history.commits

    assert _changes(c1) == [("a.txt", 3, 0, False), ("sub/b.txt", 2, 0, False)]
    assert _changes(c2) == [("a.txt", 2, 1, False)]
    assert _changes(c3) == [("renamed.txt", 1, 0, False)]  # rename attributed to new path
    assert _changes(c4) == [("bin.dat", None, None, True)]  # binary excluded from counts
    assert _changes(b1) == [("sub/b.txt", 1, 0, False)]

    assert sum(c.added for c in history.commits) == 9
    assert sum(c.removed for c in history.commits) == 1
    assert sum(c.churn for c in history.commits) == 10

    totals: dict[str, tuple[int, int]] = {}
    for commit in history.commits:
        for change in commit.changes:
            added, removed = totals.get(change.path, (0, 0))
            totals[change.path] = (
                added + (change.added or 0),
                removed + (change.removed or 0),
            )
    assert totals == {
        "a.txt": (5, 1),
        "renamed.txt": (1, 0),
        "bin.dat": (0, 0),
        "sub/b.txt": (3, 0),
    }


def test_author_metadata(history_repo: Path) -> None:
    history = log_parser.parse_history(history_repo)
    b1, c4, c3, c2, c1 = history.commits

    assert c2.author_name == "Bob"
    assert c2.author_email == "bob@example.com"
    assert c2.author_ts == 1704101000
    assert c2.committer_name == "Committer"
    assert c2.committer_email == "committer@example.com"
    # no .mailmap present: identities pass through unchanged
    assert history.author_identity(c2) == Identity("Bob", "bob@example.com")


def test_ref_parameter(history_repo: Path) -> None:
    history = log_parser.parse_history(history_repo, ref="feature")
    expected = _git(history_repo, "rev-list", "--no-merges", "feature").split()
    assert [c.hash for c in history.commits] == expected
    assert history.head == expected[0]


def test_empty_repository_raises(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    with pytest.raises(log_parser.GitParseError):
        log_parser.parse_history(repo)


def test_pure_rename_and_weird_paths(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    weird_names = ["wéird näme.txt", 'quo"te.txt', "tab\tname.txt", "line\nbreak.txt"]
    (repo / "plain.txt").write_text("keep\n", encoding="utf-8")
    for name in weird_names:
        (repo / name).write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "c1")

    _git(repo, "mv", "plain.txt", "moved.txt")
    _git(
        repo,
        "commit",
        "--quiet",
        "-m",
        "c2",
        GIT_AUTHOR_DATE="@1704101000 +0000",
        GIT_COMMITTER_DATE="@1704101000 +0000",
    )

    history = log_parser.parse_history(repo)
    assert len(history.commits) == 2
    c2, c1 = history.commits
    assert _changes(c2) == [("moved.txt", 0, 0, False)]  # pure rename: R100
    assert {c.path for c in c1.changes} == {"plain.txt", *weird_names}


def test_mailmap_is_loaded_from_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / ".mailmap").write_text(
        "Alice Proper <alice.proper@example.com> <alice@example.com>\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "add mailmap")
    (repo / "f.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "--quiet",
        "-m",
        "c2",
        GIT_AUTHOR_DATE="@1704101000 +0000",
        GIT_COMMITTER_DATE="@1704101000 +0000",
    )

    history = log_parser.parse_history(repo)
    newest = history.commits[0]
    assert newest.author_name == "Alice"  # raw data is preserved untouched
    assert history.author_identity(newest) == Identity(
        "Alice Proper", "alice.proper@example.com"
    )


class TestMailmap:
    def test_rename_only(self) -> None:
        mailmap = Mailmap.parse("Dave Smith <dave@example.com>\n")
        assert mailmap.resolve("D. Smith", "dave@example.com") == Identity(
            "Dave Smith", "dave@example.com"
        )

    def test_email_only(self) -> None:
        mailmap = Mailmap.parse("<proper@example.com> <commit@example.com>\n")
        assert mailmap.resolve("Some Name", "commit@example.com") == Identity(
            "Some Name", "proper@example.com"
        )

    def test_name_and_email(self) -> None:
        mailmap = Mailmap.parse("Proper Name <proper@example.com> <commit@example.com>\n")
        assert mailmap.resolve("Old Name", "commit@example.com") == Identity(
            "Proper Name", "proper@example.com"
        )

    def test_name_and_email_requires_name_match(self) -> None:
        mailmap = Mailmap.parse(
            "Proper Name <proper@example.com> Old Name <commit@example.com>\n"
        )
        assert mailmap.resolve("Old Name", "commit@example.com") == Identity(
            "Proper Name", "proper@example.com"
        )
        assert mailmap.resolve("Other Name", "commit@example.com") == Identity(
            "Other Name", "commit@example.com"
        )

    def test_email_match_is_case_insensitive(self) -> None:
        mailmap = Mailmap.parse("Proper Name <proper@example.com> <commit@example.com>\n")
        assert mailmap.resolve("Old Name", "COMMIT@EXAMPLE.COM") == Identity(
            "Proper Name", "proper@example.com"
        )

    def test_first_match_wins(self) -> None:
        mailmap = Mailmap.parse(
            "<first@example.com> <commit@example.com>\n"
            "<second@example.com> <commit@example.com>\n"
        )
        assert mailmap.resolve("X", "commit@example.com") == Identity("X", "first@example.com")

    def test_comments_and_blank_lines(self) -> None:
        text = "# heading\n\nProper Name <proper@example.com> <commit@example.com> # trailing\n"
        mailmap = Mailmap.parse(text)
        assert mailmap.resolve("Old", "commit@example.com") == Identity(
            "Proper Name", "proper@example.com"
        )

    def test_unmatched_and_malformed_lines(self) -> None:
        mailmap = Mailmap.parse("<lonely@example.com>\nnot a mailmap line\n")
        assert mailmap.resolve("Someone", "someone@example.com") == Identity(
            "Someone", "someone@example.com"
        )
