"""Rule34.xxx API client — authenticated search, pagination, rate limiting."""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional
import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.rule34.xxx/index.php"


@dataclass
class Post:
    """A single rule34.xxx post."""
    id: int
    tags: str
    file_url: str
    sample_url: str
    preview_url: str
    width: int
    height: int
    hash: str
    image: str
    directory: int
    change: int
    owner: str
    parent_id: int
    rating: str
    score: int
    source: str
    status: str
    sample: bool = False
    sample_height: int = 0
    sample_width: int = 0
    has_notes: bool = False
    comment_count: int = 0

    @property
    def tag_list(self) -> list[str]:
        """Return tags as a list."""
        return self.tags.split()

    @property
    def ext(self) -> str:
        """File extension from image filename."""
        return self.image.rsplit(".", 1)[-1] if "." in self.image else ""

    @property
    def filename(self) -> str:
        """Canonical filename: id_hash.ext"""
        return f"{self.id}_{self.hash}.{self.ext}"

    @classmethod
    def from_dict(cls, data: dict) -> "Post":
        return cls(
            id=int(data["id"]),
            tags=data.get("tags", ""),
            file_url=data.get("file_url", ""),
            sample_url=data.get("sample_url", ""),
            preview_url=data.get("preview_url", ""),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            hash=data.get("hash", ""),
            image=data.get("image", ""),
            directory=int(data.get("directory", 0)),
            change=int(data.get("change", 0)),
            owner=data.get("owner", ""),
            parent_id=int(data.get("parent_id", 0)),
            rating=data.get("rating", "unknown"),
            score=int(data.get("score", 0)),
            source=data.get("source", ""),
            status=data.get("status", "active"),
            sample=bool(data.get("sample", False)),
            sample_height=int(data.get("sample_height", 0)),
            sample_width=int(data.get("sample_width", 0)),
            has_notes=bool(data.get("has_notes", False)),
            comment_count=int(data.get("comment_count", 0)),
        )


class Rule34API:
    """Authenticated client for the rule34.xxx API."""

    def __init__(
        self,
        user_id: str,
        api_key: str,
        delay: float = 1.0,
        timeout: int = 30,
    ):
        self.user_id = user_id
        self.api_key = api_key
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "rule34-tool/1.0 (Hermes CLI tool; github.com/alexoutest2000-del/rule34-tool)",
        })
        self._last_request = 0.0

    @classmethod
    def from_credentials(cls, credentials: str, delay: float = 1.0, timeout: int = 30):
        """Parse &api_key=...&user_id=... into separate fields."""
        import urllib.parse
        params = urllib.parse.parse_qsl(credentials.lstrip("&"))
        parsed = dict(params)
        api_key = parsed.get("api_key", "")
        user_id = parsed.get("user_id", "")
        return cls(user_id=user_id, api_key=api_key, delay=delay, timeout=timeout)

    def _rate_limit(self):
        """Enforce minimum delay between API calls."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _get(self, params: dict) -> list[dict]:
        """Make an authenticated GET request to the API.

        Passes credentials as &api_key=...&user_id=... (rule34.xxx format).
        Returns parsed JSON list (the API returns a flat array).
        """
        params.setdefault("page", "dapi")
        params.setdefault("s", "post")
        params.setdefault("q", "index")
        params.setdefault("json", "1")
        params["api_key"] = self.api_key
        params["user_id"] = self.user_id

        self._rate_limit()

        resp = self.session.get(
            API_BASE,
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list):
            logger.warning("Unexpected API response type: %s", type(data))
            return []
        return data

    def search(
        self,
        tags: list[str],
        limit: int = 100,
        page: int = 0,
    ) -> list[Post]:
        """Search posts by tags.

        Args:
            tags: List of tag strings (space-separated in the actual query).
            limit: Results per page (max 1000).
            page: Page number (0-based).

        Returns:
            List of Post objects.
        """
        params = {
            "tags": " ".join(tags),
            "limit": min(limit, 1000),
            "pid": page,
        }
        data = self._get(params)
        return [Post.from_dict(p) for p in data]

    def search_all(
        self,
        tags: list[str],
        max_results: int = 500,
        page_size: int = 100,
    ) -> list[Post]:
        """Paginate through all results until max_results or exhaustion.

        Args:
            tags: Tag list to search.
            max_results: Stop after collecting this many posts.
            page_size: Results per API call.

        Returns:
            Combined list of Post objects across all pages.
        """
        all_posts = []
        page = 0
        remaining = max_results

        while remaining > 0:
            fetch = min(remaining, page_size, 1000)
            posts = self.search(tags, limit=fetch, page=page)
            if not posts:
                break  # no more results

            all_posts.extend(posts)
            remaining -= len(posts)
            page += 1

            if len(posts) < fetch:
                break  # last page (fewer than requested)

            logger.debug(
                "Fetched page %d: %d posts (total: %d, remaining: %d)",
                page - 1, len(posts), len(all_posts), remaining,
            )

        return all_posts

    def get_post(self, post_id: int) -> Optional[Post]:
        """Fetch a single post by ID."""
        params = {"id": post_id, "limit": 1}
        data = self._get(params)
        if data:
            return Post.from_dict(data[0])
        return None
