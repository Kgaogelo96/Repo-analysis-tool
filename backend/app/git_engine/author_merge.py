"""Persisted manual author merge rules layered on top of .mailmap."""
import json
from pathlib import Path

from app import config
from app.git_engine.mailmap import Identity

MERGES_DIR = "author_merges"
MERGES_VERSION = 1


def _merge_file(repo_id: str) -> Path:
    directory = config.workspace_dir() / MERGES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{repo_id}.json"


def _identity_from_payload(value: object) -> Identity | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("name", "")).strip()
    email = str(value.get("email", "")).strip()
    if not name and not email:
        return None
    return Identity(name=name, email=email)


def _key(identity: Identity | tuple[str, str]) -> tuple[str, str]:
    if isinstance(identity, Identity):
        return (identity.name.strip().lower(), identity.email.strip().lower())
    return (str(identity[0]).strip().lower(), str(identity[1]).strip().lower())


def load_rules(repo_id: str) -> list[dict]:
    """Load raw persisted merge rules for an ingested repository."""
    path = _merge_file(repo_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    rules = payload.get("rules", [])
    return rules if isinstance(rules, list) else []


def save_rule(repo_id: str, target: Identity, sources: list[Identity]) -> list[dict]:
    """Persist/replace source mappings for a target and return all rules."""
    existing = load_rules(repo_id)
    source_keys = {_key(source) for source in sources}
    target_key = _key(target)
    retained: list[dict] = []
    for rule in existing:
        raw_sources = rule.get("sources") if isinstance(rule, dict) else None
        if not isinstance(raw_sources, list):
            continue
        filtered = []
        for source in raw_sources:
            ident = _identity_from_payload(source)
            if ident is None:
                continue
            if _key(ident) not in source_keys and _key(ident) != target_key:
                filtered.append({"name": ident.name, "email": ident.email})
        if filtered:
            raw_target = _identity_from_payload(rule.get("target"))
            if raw_target is not None:
                retained.append(
                    {
                        "target": {"name": raw_target.name, "email": raw_target.email},
                        "sources": filtered,
                    }
                )
    retained.append(
        {
            "target": {"name": target.name, "email": target.email},
            "sources": [{"name": source.name, "email": source.email} for source in sources],
        }
    )
    path = _merge_file(repo_id)
    path.write_text(
        json.dumps({"version": MERGES_VERSION, "rules": retained}, indent=2),
        encoding="utf-8",
    )
    return retained


def resolver(repo_id: str) -> dict[tuple[str, str], Identity]:
    """Return a source identity lookup for manual merges."""
    mapping: dict[tuple[str, str], Identity] = {}
    for rule in load_rules(repo_id):
        target = _identity_from_payload(rule.get("target")) if isinstance(rule, dict) else None
        raw_sources = rule.get("sources") if isinstance(rule, dict) else None
        if target is None or not isinstance(raw_sources, list):
            continue
        mapping[_key(target)] = target
        for raw_source in raw_sources:
            source = _identity_from_payload(raw_source)
            if source is not None:
                mapping[_key(source)] = target
    return mapping


def resolve_author(
    mapping: dict[tuple[str, str], Identity],
    raw_name: str,
    raw_email: str,
    canonical: Identity,
) -> Identity:
    """Apply persisted manual merges after .mailmap canonicalization."""
    return mapping.get(_key((raw_name, raw_email))) or mapping.get(_key(canonical)) or canonical


def delete_rules(repo_id: str) -> None:
    """Delete persisted manual merges for a removed repository."""
    try:
        _merge_file(repo_id).unlink(missing_ok=True)
    except OSError:
        pass
