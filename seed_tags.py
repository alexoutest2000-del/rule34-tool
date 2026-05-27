#!/usr/bin/env python3
"""Seed the tag cache by fetching the first 100 pages of the tag listing."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rule34.config import Config
from rule34.api import Rule34API
from rule34.tag_cache import load_cache, save_cache, add_tags

cfg = Config.load()
if not cfg.has_credentials:
    print("No API credentials configured. Run ./run.sh first and set credentials in Settings.")
    sys.exit(1)

api = Rule34API(user_id=cfg.user_id, api_key=cfg.api_key, delay=0.3)

cache = load_cache()
print(f"Existing cache: {len(cache)} tags")

PAGES = 200   # first 200 pages of tag listing
PAGE_SIZE = 100

new_total = 0
for page in range(PAGES):
    try:
        posts = api.search(["1girl"], limit=PAGE_SIZE, page=page)
        if not posts:
            print(f"  Page {page}: no results, stopping.")
            break
        all_tags = []
        for p in posts:
            all_tags.extend(p.tag_list)
        cache = add_tags(cache, all_tags)
        new_total += len(posts)
        print(f"  Page {page}: {len(posts)} posts, cache now {len(cache)} tags", end="\r")
    except Exception as e:
        print(f"\n  Page {page}: error: {e}")
        break

print(f"\nDone. {new_total} posts processed, cache has {len(cache)} tags.")
