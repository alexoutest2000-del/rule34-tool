#!/usr/bin/env python3
"""rule34-tool — Search, preview, and download from rule34.xxx.

Usage:
    r34 search <tags...>        Search and show results
    r34 preview <tags...>       Search and open HTML preview gallery
    r34 download <tags...>      Search and download matching images
    r34 download --ids 1,2,3    Download specific post IDs
    r34 config                  Show/set configuration
"""

import sys
import argparse
import webbrowser
from pathlib import Path

from rule34.api import Rule34API
from rule34.config import Config, DEFAULT_CONFIG_PATH
from rule34.preview import generate_gallery


def get_api(cfg: Config) -> Rule34API:
    if not cfg.user_id or not cfg.api_key:
        print("Error: API credentials not configured.", file=sys.stderr)
        print(f"  Run: r34 config set  — or create {DEFAULT_CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    return Rule34API(
        user_id=cfg.user_id,
        api_key=cfg.api_key,
        delay=cfg.delay,
        timeout=cfg.timeout,
    )


def cmd_search(args, cfg: Config):
    """Search and list results in terminal."""
    api = get_api(cfg)
    posts = api.search(args.tags, limit=args.limit)

    if not posts:
        print("No results found.")
        return

    print(f"\n{'─'*70}")
    print(f"  Tags: {' '.join(args.tags)}  |  {len(posts)} results  |  Limit: {args.limit}")
    print(f"{'─'*70}")
    for p in posts:
        tags_preview = " ".join(p.tag_list[:5])
        if len(p.tag_list) > 5:
            tags_preview += f" (+{len(p.tag_list) - 5})"
        print(f"  [{p.id}] {p.width}×{p.height}  {p.rating:6s}  {tags_preview}")
        print(f"        {p.preview_url}")

    if len(posts) >= args.limit:
        print(f"\n  ⚠ Showing first {args.limit} results. Use --limit for more (max 1000).")
        print(f"  To see all: r34 preview {' '.join(args.tags)} --limit {args.limit * 2}")


def cmd_preview(args, cfg: Config):
    """Search and open HTML preview gallery."""
    api = get_api(cfg)

    print(f"Searching: {' '.join(args.tags)}...")
    if args.max_results:
        posts = api.search_all(args.tags, max_results=args.max_results, page_size=min(args.limit, 100))
    else:
        posts = api.search(args.tags, limit=args.limit)

    if not posts:
        print("No results found.")
        return

    output_path = Path(args.output or "rule34_gallery.html")
    path = generate_gallery(posts, args.tags, output_path=output_path)

    print(f"\n✓ {len(posts)} results → {path.resolve()}")
    print(f"  Select images with checkboxes, then copy the download command from the bottom bar.")

    if not args.no_open:
        webbrowser.open(str(path.resolve()))


def cmd_download(args, cfg: Config):
    """Download images by tags or specific IDs."""
    api = get_api(cfg)

    # Determine which posts to download
    if args.ids:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        posts = []
        for pid in ids:
            post = api.get_post(pid)
            if post:
                posts.append(post)
            else:
                print(f"  ⚠ Post {pid} not found, skipping.")
        print(f"Fetching {len(posts)}/{len(ids)} posts by ID...")
    elif args.tags:
        print(f"Searching: {' '.join(args.tags)}...")
        posts = api.search_all(args.tags, max_results=args.max_results or args.limit, page_size=100)
        print(f"Found {len(posts)} posts.")
    else:
        print("Error: specify --tags or --ids", file=sys.stderr)
        sys.exit(1)

    if not posts:
        print("Nothing to download.")
        return

    # Download
    output_dir = Path(args.output or cfg.download_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    import requests
    from tqdm import tqdm

    print(f"\nDownloading {len(posts)} images to {output_dir}/")
    success = 0
    skipped = 0
    failed = 0

    for post in tqdm(posts, desc="Downloading", unit="img"):
        dest = output_dir / post.filename
        if dest.exists():
            skipped += 1
            continue

        try:
            resp = requests.get(post.file_url, timeout=cfg.timeout, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            success += 1
        except Exception as e:
            failed += 1
            tqdm.write(f"  ✗ {post.filename}: {e}")

    print(f"\n✓ {success} downloaded, {skipped} skipped, {failed} failed")
    print(f"  Directory: {output_dir.resolve()}")


def cmd_config(args, cfg: Config):
    """Manage configuration."""
    if args.action == "show":
        print(f"Config file: {DEFAULT_CONFIG_PATH}")
        print(f"  user_id:  {cfg.user_id or '(not set)'}")
        print(f"  api_key:  {cfg.api_key[:8] + '...' if cfg.api_key else '(not set)'}")
        print(f"  delay:    {cfg.delay}s")
        print(f"  download: {cfg.download_dir}")
        print(f"  timeout:  {cfg.timeout}s")

    elif args.action == "set":
        print("Enter your rule34.xxx API credentials (from Account → Options):")
        cfg.user_id = input("  user_id: ").strip()
        cfg.api_key = input("  api_key: ").strip()
        cfg.save()
        print(f"✓ Saved to {DEFAULT_CONFIG_PATH}")


def main():
    parser = argparse.ArgumentParser(
        prog="r34",
        description="Search, preview, and download images from rule34.xxx",
    )
    sub = parser.add_subparsers(dest="command")

    # search
    p_search = sub.add_parser("search", help="Search and list results in terminal")
    p_search.add_argument("tags", nargs="+", help="Tags to search for")
    p_search.add_argument("--limit", "-n", type=int, default=20, help="Max results (default: 20, max: 1000)")

    # preview
    p_preview = sub.add_parser("preview", help="Search and open HTML preview gallery")
    p_preview.add_argument("tags", nargs="+", help="Tags to search for")
    p_preview.add_argument("--limit", "-n", type=int, default=100, help="Results per page (default: 100)")
    p_preview.add_argument("--max-results", "-m", type=int, default=None, help="Paginate up to N total results")
    p_preview.add_argument("--output", "-o", default="rule34_gallery.html", help="HTML output path")
    p_preview.add_argument("--no-open", action="store_true", help="Don't auto-open in browser")

    # download
    p_dl = sub.add_parser("download", help="Download images")
    p_dl.add_argument("tags", nargs="*", help="Tags to search for")
    p_dl.add_argument("--ids", help="Comma-separated post IDs to download")
    p_dl.add_argument("--limit", "-n", type=int, default=100, help="Max results")
    p_dl.add_argument("--max-results", "-m", type=int, default=None, help="Paginate up to N total")
    p_dl.add_argument("--output", "-o", default=None, help="Download directory")

    # config
    p_cfg = sub.add_parser("config", help="Manage configuration")
    p_cfg.add_argument("action", nargs="?", default="show", choices=["show", "set"])

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    cfg = Config.load()

    if args.command == "search":
        cmd_search(args, cfg)
    elif args.command == "preview":
        cmd_preview(args, cfg)
    elif args.command == "download":
        cmd_download(args, cfg)
    elif args.command == "config":
        cmd_config(args, cfg)


if __name__ == "__main__":
    main()
