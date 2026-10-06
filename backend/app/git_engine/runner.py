"""Thin subprocess wrappers around the git CLI shared by all git-facing modules."""
import os
import subprocess
from pathlib import Path
from typing import Sequence

DEFAULT_TIMEOUT = 60


class GitError(RuntimeError):
    """Raised when a git invocation cannot be executed or exits non-zero."""


def _git_env() -> dict:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")  # fail fast instead of hanging on prompts
    env["LC_ALL"] = "C"  # keep git messages in English for friendlier error mapping
    return env


def run_git(
    args: Sequence[str],
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Run `git <args>` and capture stdout/stderr.

    Pass `text=False` to receive raw bytes; required for `git log -z`, whose
    output must not be decoded as one locale-dependent string (paths are
    arbitrary byte sequences).
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=_git_env(),
            capture_output=True,
            text=text,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    if check and proc.returncode != 0:
        raise GitError(_error_message(proc, args))
    return proc


def _error_message(proc: subprocess.CompletedProcess, args: Sequence[str]) -> str:
    """Last non-empty stderr line (or stdout), decoded best-effort, as error text."""
    raw = proc.stderr or proc.stdout or b""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return lines[-1] if lines else f"git {' '.join(args)} failed"


def head_commit(repo_path: Path | str) -> str | None:
    """Resolve the commit HEAD points to; None for empty or broken repositories."""
    proc = run_git(["rev-parse", "--verify", "HEAD"], cwd=repo_path, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
