""".mailmap parsing and canonical author identity resolution."""
import re
from dataclasses import dataclass
from pathlib import Path

from app.git_engine.runner import run_git

# Matches the <email> part of a mailmap line; also used to split lines into parts.
_EMAIL_RE = re.compile(r"<([^<>]*)>")


@dataclass(frozen=True, slots=True)
class Identity:
    """Canonical author identity (possibly rewritten by the mailmap)."""

    name: str
    email: str


@dataclass(frozen=True, slots=True)
class _Rule:
    match_name: str | None  # exact commit name required; None matches any name
    match_email: str  # lowercased commit email
    proper_name: str | None  # replacement name; None keeps the original
    proper_email: str | None  # replacement email; None keeps the original


class Mailmap:
    """Parsed `.mailmap` rules; like git, the first matching rule wins."""

    def __init__(self, rules: list[_Rule] | None = None):
        self._rules = list(rules or [])

    @classmethod
    def parse(cls, text: str) -> "Mailmap":
        """Parse the four git-mailmap(5) line forms; malformed lines are skipped."""
        rules: list[_Rule] = []
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = _EMAIL_RE.split(line)
            # parts = [before, email1, between, email2, after, ...]
            if len(parts) == 3 and parts[0].strip():
                # "Proper Name <commit@email>" - rename only, email kept
                email = parts[1].strip().lower()
                if email:
                    rules.append(
                        _Rule(
                            match_name=None,
                            match_email=email,
                            proper_name=parts[0].strip(),
                            proper_email=None,
                        )
                    )
            elif len(parts) >= 5:
                # "<proper@email> <commit@email>"               - email rewrite only
                # "Name <proper@email> <commit@email>"          - name + email rewrite
                # "Name <proper@email> Commit Name <commit@email>" - both, name must match
                match_email = parts[3].strip().lower()
                if not match_email:
                    continue
                rules.append(
                    _Rule(
                        match_name=parts[2].strip() or None,
                        match_email=match_email,
                        proper_name=parts[0].strip() or None,
                        proper_email=parts[1].strip() or None,
                    )
                )
        return cls(rules)

    def resolve(self, name: str, email: str) -> Identity:
        """Resolve a raw author; emails match case-insensitively, names exactly."""
        email_key = (email or "").strip().lower()
        for rule in self._rules:
            if rule.match_email != email_key:
                continue
            if rule.match_name is not None and rule.match_name != name:
                continue
            return Identity(
                name=rule.proper_name if rule.proper_name is not None else name,
                email=rule.proper_email if rule.proper_email is not None else email,
            )
        return Identity(name=name, email=email)


def load_mailmap(repo_path: Path | str, ref: str = "HEAD") -> Mailmap:
    """Load `.mailmap` from `ref` (committed form), falling back to the working tree."""
    proc = run_git(["show", f"{ref}:.mailmap"], cwd=repo_path, check=False, text=False)
    if proc.returncode == 0 and proc.stdout.strip():
        return Mailmap.parse(proc.stdout.decode("utf-8", "replace"))
    path = Path(repo_path) / ".mailmap"
    if path.is_file():
        return Mailmap.parse(path.read_text(encoding="utf-8", errors="replace"))
    return Mailmap()
