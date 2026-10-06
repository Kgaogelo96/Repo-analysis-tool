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
) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=_git_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    if check and proc.returncode != 0:
        lines = [line for line in (proc.stderr or proc.stdout or "").splitlines() if line.strip()]
        raise GitError(lines[-1].strip() if lines else f"git {' '.join(args)} failed")
    return proc


def head_commit(repo_path: Path | str) -> str | None:
    """Resolve the commit HEAD points to; None for empty or broken repositories."""
    proc = run_git(["rev-parse", "--verify", "HEAD"], cwd=repo_path, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
