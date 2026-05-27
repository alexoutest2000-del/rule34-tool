"""Local tag cache for autocomplete — builds from search results over time.
Stores tag → type mapping for category color-coding.
Tag types: 0=general, 1=artist, 3=copyright, 4=character, 5=metadata
"""

import json
from pathlib import Path
from typing import Optional

CACHE_FILE = Path(__file__).resolve().parent.parent / "tags_cache.json"

# Type name mapping
TAG_TYPE_NAMES = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "metadata"}


def load_cache() -> dict[str, int]:
    """Load cached tags from disk. Returns {tag: type} dict."""
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                # Legacy format — bare list, no types
                return {t: 0 for t in data}
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_cache(tags: dict[str, int]) -> None:
    """Save tag→type dict to disk as sorted JSON."""
    CACHE_FILE.write_text(json.dumps(dict(sorted(tags.items())), indent=2))


def add_tags(tags: dict[str, int], new_tags: list[str], tag_type: int = 0) -> dict[str, int]:
    """Add new tags with their type. Returns updated dict."""
    added = 0
    for t in new_tags:
        t = t.strip().lower()
        if t and t not in tags:
            tags[t] = tag_type
            added += 1
        elif t and tags.get(t, 0) == 0 and tag_type != 0:
            # Upgrade type if we now know it
            tags[t] = tag_type
    if added:
        save_cache(tags)
    return tags


def add_tag_types(tags: dict[str, int], type_map: dict[str, int]) -> dict[str, int]:
    """Bulk-add/update tag types from a {tag: type} mapping."""
    changed = False
    for tag, ttype in type_map.items():
        tag = tag.strip().lower()
        if not tag:
            continue
        if tag not in tags:
            tags[tag] = ttype
            changed = True
        elif tags.get(tag, 0) == 0 and ttype != 0:
            tags[tag] = ttype
            changed = True
    if changed:
        save_cache(tags)
    return tags


def search(tags: dict[str, int], prefix: str, limit: int = 20) -> list[str]:
    """Return tags starting with the given prefix."""
    prefix = prefix.lower()
    matches = [t for t in tags if t.startswith(prefix)]
    matches.sort()
    return matches[:limit]


def get_type(tags: dict[str, int], tag: str) -> int:
    """Get the type of a tag (0=general if unknown)."""
    return tags.get(tag.strip().lower(), 0)


def get_type_name(tags: dict[str, int], tag: str) -> str:
    """Get the human-readable type name of a tag."""
    return TAG_TYPE_NAMES.get(get_type(tags, tag), "general")
