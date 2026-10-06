"""Metrics engine tests against synthetic repositories with hand-computed totals."""
import os
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import data_store, state
from app.api.routes_metrics import _safe_text
from app.git_engine import log_parser
from app.main import app
from app.metrics import aggregator, author_metrics, dir_metrics, file_metrics

# All eight commits land on 2024-01-01 (Monday), so day/week/month bucketing
# collapses into a single bucket with a known start timestamp.
T0, T1, T2, T3 = 1704100000, 1704101000, 1704102000, 1704103000
T4, T5, T5_5, T6, T7 = 1704104000, 1704105000, 1704105500, 1704106000, 1704107000

_BASE_ENV = {
    "GIT_AUTHOR_NAME": "Alice",
    "GIT_AUTHOR_EMAIL": "alice@example.com",
    "GIT_AUTHOR_DATE": f"@{T0} +0000",
    "GIT_COMMITTER_NAME": "Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.com",
    "GIT_COMMITTER_DATE": f"@{T0} +0000",
}


def _git(repo: Path, *args: str, **env_overrides: str) -> None:
    env = os.environ.copy()
    env.update(_BASE_ENV)
    env.update(env_overrides)
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _commit_as(repo: Path, name: str, email: str, ts: int, *args: str) -> None:
    _git(
        repo,
        *args,
        GIT_AUTHOR_NAME=name,
        GIT_AUTHOR_EMAIL=email,
        GIT_AUTHOR_DATE=f"@{ts} +0000",
        GIT_COMMITTER_DATE=f"@{ts} +0000",
    )


def _build_repo(base: Path) -> Path:
    """Eight non-merge commits (add/rename/binary/empty, four authors) plus a merge.

    Ground truth, no filters: commits=8, entries=9, added=26, removed=1,
    churn=27, files=7, authors=4 (Alice 18 churn, Bob 8, Dave 1, Carol 0).
    """
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet", "--initial-branch=main")
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "assets").mkdir()

    (repo / "src" / "app.py").write_text(
        "\n".join(f"app{i}" for i in range(10)) + "\n", encoding="utf-8"
    )
    (repo / "README.md").write_text(
        "\n".join(f"readme{i}" for i in range(5)) + "\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _commit_as(repo, "Alice", "alice@example.com", T0, "commit", "--quiet", "-m", "c1")

    (repo / "src" / "util.py").write_text(
        "\n".join(f"u{i}" for i in range(4)) + "\n", encoding="utf-8"
    )
    (repo / "docs" / "guide.md").write_text(
        "\n".join(f"g{i}" for i in range(3)) + "\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _commit_as(repo, "Bob", "bob@example.com", T1, "commit", "--quiet", "-m", "c2")

    lines = [f"app{i}" for i in range(10)]  # edit one line (+1 -1), append one (+1)
    lines[0] = "app0-edited"
    lines.append("app-new")
    (repo / "src" / "app.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _git(repo, "add", ".")
    _commit_as(repo, "Alice", "alice@example.com", T2, "commit", "--quiet", "-m", "c3")

    (repo / "assets" / "logo.png").write_bytes(b"\x00\x01\x02\x03png")
    _git(repo, "add", ".")
    _commit_as(repo, "Carol", "carol@example.com", T3, "commit", "--quiet", "-m", "c4")

    _git(repo, "mv", "docs/guide.md", "docs/manual.md")  # 75% similar: rename + edit
    (repo / "docs" / "manual.md").write_text(
        "\n".join(f"g{i}" for i in range(3)) + "g-new\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _commit_as(repo, "Bob", "bob@example.com", T4, "commit", "--quiet", "-m", "c5")

    _git(repo, "mv", "src/util.py", "src/helper.py")  # pure rename: 0/0
    _commit_as(repo, "Alice", "alice@example.com", T5, "commit", "--quiet", "-m", "c6")

    _git(repo, "checkout", "--quiet", "-b", "feature")
    with (repo / "src" / "app.py").open("a", encoding="utf-8") as fh:
        fh.write("feature-line\n")
    _git(repo, "add", ".")
    _commit_as(repo, "Dave", "dave@example.com", T5_5, "commit", "--quiet", "-m", "b1")
    _git(repo, "checkout", "--quiet", "main")
    _commit_as(
        repo, "Alice", "alice@example.com", T6,
        "merge", "--quiet", "--no-ff", "-m", "merge feature", "feature",
    )

    _commit_as(  # empty commit: counted without a path filter, never with one
        repo, "Alice", "alice@example.com", T7,
        "commit", "--quiet", "--allow-empty", "-m", "c7",
    )
    return repo


def _select(history, **filters):
    aggregate = aggregator.build_aggregate(history)
    return aggregator.select(aggregate, aggregator.Filters(**filters))


@pytest.fixture()
def history_repo(tmp_path: Path) -> log_parser.ParsedHistory:
    return log_parser.parse_history(_build_repo(tmp_path))


# --- aggregator ---------------------------------------------------------------------


def test_aggregate_totals(history_repo: log_parser.ParsedHistory) -> None:
    aggregate = aggregator.build_aggregate(history_repo)
    assert len(aggregate.commits) == 8  # merge excluded
    assert len(aggregate.entries) == 9
    assert sum(c.added for c in aggregate.commits) == 26
    assert sum(c.removed for c in aggregate.commits) == 1
    timestamps = [c.author_ts for c in aggregate.commits]
    assert timestamps == sorted(timestamps, reverse=True)  # newest first
    assert aggregate.commits[0].files == 0  # c7 is the empty commit
    assert len(aggregate.authors) == 4


def test_aggregate_cache_reuse(history_repo: log_parser.ParsedHistory) -> None:
    first = aggregator.get_or_build("metrics-cache-test", history_repo)
    try:
        assert aggregator.get_or_build("metrics-cache-test", history_repo) is first
    finally:
        aggregator.invalidate("metrics-cache-test")
    assert aggregator.get_or_build("metrics-cache-test", history_repo) is not first
    aggregator.invalidate("metrics-cache-test")


# --- file / author / directory metrics ----------------------------------------------


def test_file_stats(history_repo: log_parser.ParsedHistory) -> None:
    stats = file_metrics.file_stats(_select(history_repo))
    assert len(stats) == 7

    app = stats["src/app.py"]  # c1 +10, c3 +2 -1, b1 +1
    assert (app.added, app.removed) == (13, 1)
    assert (app.churn, app.growth) == (14, 12)
    assert len(app.commits) == 3
    assert len(app.authors) == 2  # Alice and Dave
    assert app.last_ts == T5_5

    helper = stats["src/helper.py"]  # pure rename target, zero lines
    assert (helper.added, helper.removed) == (0, 0)
    assert len(helper.commits) == 1 and helper.last_ts == T5

    logo = stats["assets/logo.png"]  # binary: touched but never line-counted
    assert (logo.added, logo.removed) == (0, 0)
    assert len(logo.binary_commits) == 1


def test_author_stats_and_ownership(history_repo: log_parser.ParsedHistory) -> None:
    stats = author_metrics.author_stats(_select(history_repo))
    assert [stat.author.name for stat in stats] == ["Alice", "Bob", "Dave", "Carol"]

    alice = stats[0]
    assert len(alice.commits) == 4  # includes the empty c7
    assert (alice.added, alice.removed) == (17, 1)
    assert alice.files == {"src/app.py", "README.md", "src/helper.py"}
    assert (alice.first_ts, alice.last_ts) == (T0, T7)
    assert alice.ownership == pytest.approx(18 / 27)
    assert sum(stat.ownership for stat in stats) == pytest.approx(1.0)
    assert len(stats[1].commits) == 2  # Bob: c2 + c5
    assert stats[2].churn == 1  # Dave
    assert stats[3].churn == 0 and stats[3].ownership == 0.0  # Carol: binary only


def test_directory_rollup(history_repo: log_parser.ParsedHistory) -> None:
    stats = file_metrics.file_stats(_select(history_repo))
    tree = dir_metrics.directory_rollup(stats)
    assert tree["kind"] == "dir" and tree["path"] == ""
    assert tree["files"] == 7 and (tree["added"], tree["removed"]) == (26, 1)
    # dirs first (alphabetical), then files
    assert [child["name"] for child in tree["children"]] == [
        "assets", "docs", "src", "README.md",
    ]

    by_name = {child["name"]: child for child in tree["children"]}
    assert by_name["assets"]["binary_commits"] == 1 and by_name["assets"]["added"] == 0
    assert by_name["docs"]["files"] == 2 and by_name["docs"]["commits"] == 2
    src = by_name["src"]
    assert src["files"] == 3 and src["commits"] == 5
    assert (src["added"], src["removed"]) == (17, 1)

    app = next(c for c in src["children"] if c["name"] == "app.py")
    assert app["kind"] == "file" and app["commits"] == 3 and app["authors"] == 2
    assert (app["added"], app["removed"]) == (13, 1)


def test_commit_set_totals(history_repo: log_parser.ParsedHistory) -> None:
    totals = dir_metrics.commit_set_totals(_select(history_repo))
    assert totals["commits"] == 8  # empty commit included without a path filter
    assert totals["authors"] == 4 and totals["files"] == 7 and totals["binary_files"] == 1
    assert (totals["added"], totals["removed"]) == (26, 1)
    assert (totals["churn"], totals["growth"]) == (27, 25)
    assert (totals["first_ts"], totals["last_ts"]) == (T0, T7)
    assert totals["avg_churn_per_commit"] == round(27 / 8, 2)


# --- filter semantics ---------------------------------------------------------------


def test_time_filters(history_repo: log_parser.ParsedHistory) -> None:
    totals = dir_metrics.commit_set_totals(_select(history_repo, since=T2, until=T4))
    assert totals["commits"] == 2  # c3 inclusive at since, c5 excluded at until
    assert (totals["added"], totals["removed"]) == (2, 1)


def test_author_filter(history_repo: log_parser.ParsedHistory) -> None:
    def total(**kwargs):
        return dir_metrics.commit_set_totals(_select(history_repo, **kwargs))

    assert total(author="bob")["commits"] == 2  # canonical/raw substring
    assert total(author="BOB@EXAMPLE.COM")["commits"] == 2  # case-insensitive email
    assert total(author="alice", path="src")["commits"] == 3  # combined filters
    empty = total(author="nobody-at-all")
    assert empty["commits"] == 0 and empty["churn"] == 0 and empty["first_ts"] is None


def test_path_filter_prefix_and_exact(history_repo: log_parser.ParsedHistory) -> None:
    def total(path: str):
        return dir_metrics.commit_set_totals(_select(history_repo, path=path))

    assert total("src")["commits"] == 5  # prefix; empty commit drops out
    assert total("src")["files"] == 3 and total("src")["added"] == 17
    assert total("src/app.py")["commits"] == 3  # exact file
    assert (total("src/app.py")["added"], total("src/app.py")["removed"]) == (13, 1)
    assert total("src/missing")["commits"] == 0


def test_hash_whitelist(history_repo: log_parser.ParsedHistory) -> None:
    hashes = {
        c.hash for c in aggregator.build_aggregate(history_repo).commits
        if c.author_ts in (T0, T5)
    }
    selection = _select(history_repo, hashes=frozenset(h[:8] for h in hashes))
    totals = dir_metrics.commit_set_totals(selection)
    assert totals["commits"] == 2  # short prefixes match
    assert totals["added"] == 15  # c1 (15) + c6 (pure rename, 0)


def test_empty_selection_is_zeroed(history_repo: log_parser.ParsedHistory) -> None:
    selection = _select(history_repo, author="zzz")
    assert dir_metrics.commit_set_totals(selection) == {
        "commits": 0, "authors": 0, "files": 0, "binary_files": 0,
        "added": 0, "removed": 0, "churn": 0, "growth": 0,
        "first_ts": None, "last_ts": None, "avg_churn_per_commit": 0.0,
    }
    assert author_metrics.author_stats(selection) == []
    assert file_metrics.file_stats(selection) == {}
    assert dir_metrics.directory_rollup({})["files"] == 0
    assert dir_metrics.timeseries(selection)["points"] == []


def test_timeseries_buckets(history_repo: log_parser.ParsedHistory) -> None:
    selection = _select(history_repo)
    series = dir_metrics.timeseries(selection, "day")
    assert series["bucket"] == "day" and series["bucket_seconds"] == 86400
    (point,) = series["points"]
    assert point["start_ts"] == 1704067200  # 2024-01-01T00:00:00Z
    assert point["commits"] == 7  # the empty commit has no bucketable activity
    assert (point["added"], point["removed"], point["growth"]) == (26, 1, 25)

    fallback = dir_metrics.timeseries(selection, "fortnight")  # unknown -> month
    assert fallback["bucket"] == "month" and fallback["bucket_seconds"] is None
    assert fallback["points"] == series["points"]


def test_mailmap_grouping(tmp_path: Path) -> None:
    repo = tmp_path / "mapped"
    repo.mkdir()
    _git(repo, "init", "--quiet", "--initial-branch=main")
    (repo / ".mailmap").write_text(
        "Robert B <robert@example.com> <bob@example.com>\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _commit_as(repo, "Alice", "alice@example.com", T0, "commit", "--quiet", "-m", "mailmap")
    (repo / "f.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _commit_as(repo, "Bob", "bob@example.com", T1, "commit", "--quiet", "-m", "c2")

    history = log_parser.parse_history(repo)
    stats = author_metrics.author_stats(_select(history))
    assert {stat.author.name for stat in stats} == {"Alice", "Robert"}
    robert = next(stat for stat in stats if stat.author.name == "Robert")
    assert robert.author.email == "robert@example.com"
    assert len(robert.commits) == 1 and robert.added == 1


# --- API endpoints ------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _seed_ready(repo: Path) -> str:
    """Register a repo as ready without going through the zip upload path."""
    repo_id = state.new_repo_id()
    history = log_parser.parse_history(repo)
    data_store.put(repo_id, history)
    state.registry().create(
        repo_id=repo_id, name="seeded", source="zip", origin="seed", path=str(repo)
    )
    state.registry().update(
        repo_id, status="ready", head=history.head, commit_count=len(history.commits)
    )
    return repo_id


def _unseed(repo_id: str) -> None:
    state.registry().remove(repo_id)
    data_store.invalidate(repo_id)
    aggregator.invalidate(repo_id)


@pytest.fixture()
def ready_repo(client: TestClient, tmp_path: Path) -> str:
    """Ingest the synthetic repo through the real upload pipeline."""
    repo = _build_repo(tmp_path)
    zip_path = tmp_path / "repo.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in sorted(repo.rglob("*")):
            if path.is_file():
                archive.write(path, Path("repo") / path.relative_to(repo))
    with zip_path.open("rb") as fh:
        response = client.post(
            "/api/repo/upload", files={"file": ("repo.zip", fh, "application/zip")}
        )
    assert response.status_code == 202
    repo_id = response.json()["id"]
    for _ in range(100):
        record = client.get(f"/api/repo/{repo_id}").json()
        if record["status"] in ("ready", "error"):
            assert record["status"] == "ready", record.get("error")
            break
        time.sleep(0.1)
    else:
        pytest.fail("ingestion did not finish in time")
    yield repo_id
    client.delete(f"/api/repo/{repo_id}")


def test_metric_endpoints(client: TestClient, ready_repo: str) -> None:
    rid = ready_repo

    summary = client.get(f"/api/metrics/{rid}/summary").json()
    assert summary["commits"] == 8 and (summary["added"], summary["removed"]) == (26, 1)

    authors = client.get(f"/api/metrics/{rid}/authors").json()
    assert authors["total"] == 4
    assert authors["authors"][0]["name"] == "Alice"
    assert authors["authors"][0]["ownership"] == round(18 / 27, 4)

    files = client.get(f"/api/metrics/{rid}/files").json()
    assert files["total"] == 7 and files["limit"] == 200
    assert files["files"][0]["path"] == "src/app.py"  # churn-descending default

    tree = client.get(f"/api/metrics/{rid}/tree").json()["tree"]
    assert [child["name"] for child in tree["children"]] == [
        "assets", "docs", "src", "README.md",
    ]

    series = client.get(f"/api/metrics/{rid}/timeseries").json()
    assert series["bucket"] == "month" and len(series["points"]) == 1

    identities = client.get(f"/api/metrics/{rid}/authors/identities").json()
    assert identities["total"] == 4
    assert identities["identities"][0]["raw_name"] == "Alice"
    assert identities["identities"][0]["commits"] == 4
    assert identities["identities"][0]["author"]["name"] == "Alice"

    filtered = client.get(
        f"/api/metrics/{rid}/summary", params={"author": "bob", "path": "docs"}
    ).json()
    assert filtered["commits"] == 2 and filtered["added"] == 4

    head = client.get(f"/api/repo/{rid}/commits").json()["commits"][0]["hash"]
    single = client.get(f"/api/metrics/{rid}/summary", params={"hashes": head[:7]}).json()
    assert single["commits"] == 1


def test_files_sorting_and_clamping(client: TestClient, ready_repo: str) -> None:
    base = f"/api/metrics/{ready_repo}/files"
    asc = client.get(base, params={"sort": "path", "order": "asc", "limit": 2}).json()
    assert [f["path"] for f in asc["files"]] == ["assets/logo.png", "docs/guide.md"]
    assert (asc["total"], asc["offset"], asc["limit"]) == (7, 0, 2)

    paged = client.get(base, params={"offset": 6, "limit": 10}).json()
    assert len(paged["files"]) == 1

    clamped = client.get(base, params={"limit": 999999}).json()
    assert clamped["limit"] == 1000

    fallback = client.get(base, params={"sort": "nope"}).json()  # unknown -> churn
    assert fallback["files"][0]["path"] == "src/app.py"


def test_timeseries_endpoint_buckets(client: TestClient, ready_repo: str) -> None:
    week = client.get(
        f"/api/metrics/{ready_repo}/timeseries", params={"bucket": "week"}
    ).json()
    assert week["bucket"] == "week" and week["bucket_seconds"] == 7 * 86400
    (point,) = week["points"]
    assert point["start_ts"] == 1704067200  # 2024-01-01 was a Monday


def test_unknown_and_not_ready_rejected(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/metrics/nope/summary").status_code == 404

    repo_id = state.new_repo_id()
    state.registry().create(
        repo_id=repo_id, name="pending", source="zip", origin="x", path=str(tmp_path)
    )
    try:
        probe = client.get(f"/api/metrics/{repo_id}/summary")
        assert probe.status_code == 409
    finally:
        state.registry().remove(repo_id)


def test_surrogate_paths_are_sanitized(client: TestClient, tmp_path: Path) -> None:
    repo = _build_repo(tmp_path)
    (repo / os.fsdecode(b"weird\xffname.txt")).write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _commit_as(repo, "Alice", "alice@example.com", 1704108000, "commit", "--quiet", "-m", "c8")

    repo_id = _seed_ready(repo)
    try:
        response = client.get(
            f"/api/metrics/{repo_id}/files", params={"sort": "path", "order": "asc"}
        )
        assert response.status_code == 200
        paths = [f["path"] for f in response.json()["files"]]
        assert "weird\ufffdname.txt" in paths
        assert "\udcff" not in "".join(paths)
        assert client.get(f"/api/metrics/{repo_id}/tree").status_code == 200
    finally:
        _unseed(repo_id)


def test_safe_text_repairs_surrogates() -> None:
    assert _safe_text("plain.txt") == "plain.txt"
    assert _safe_text(os.fsdecode(b"bad\xffname")) == "bad\ufffdname"
