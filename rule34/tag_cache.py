"""Local tag cache for autocomplete — builds from search results over time."""

import json
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parent.parent / "tags_cache.json"


def load_cache() -> set[str]:
    """Load cached tags from disk. Returns empty set if no cache exists."""
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            if isinstance(data, list):
                return set(data)
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def save_cache(tags: set[str]) -> None:
    """Save tag set to disk as sorted JSON list."""
    CACHE_FILE.write_text(json.dumps(sorted(tags), indent=2))


def add_tags(tags: set[str], new_tags: list[str]) -> set[str]:
    """Add new tags to the set. Returns updated set."""
    added = 0
    for t in new_tags:
        t = t.strip().lower()
        if t and t not in tags:
            tags.add(t)
            added += 1
    if added:
        save_cache(tags)
    return tags


def search(tags: set[str], prefix: str, limit: int = 20) -> list[str]:
    """Return tags starting with the given prefix."""
    prefix = prefix.lower()
    matches = [t for t in tags if t.startswith(prefix)]
    matches.sort()
    return matches[:limit]
