"""Configuration management for rule34-tool.

Reads from config.yaml (gitignored) with fallback to environment variables.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"  # project root


@dataclass
class Config:
    credentials: str = ""           # raw &api_key=...&user_id=... string
    delay: float = 1.0
    download_dir: str = "./downloads"
    timeout: int = 30

    # Derived fields (populated from credentials on load)
    user_id: str = ""
    api_key: str = ""

    @property
    def has_credentials(self) -> bool:
        return bool(self.user_id and self.api_key)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load config from file, falling back to env vars.

        Supports two formats:
          1. Single 'credentials' field: &api_key=...&user_id=...  (rule34 format)
          2. Separate 'user_id' + 'api_key' fields (legacy)
        """
        cfg = cls()

        # Try config file
        if path is None:
            path = DEFAULT_CONFIG_PATH
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            for key in ("credentials", "user_id", "api_key", "delay", "download_dir", "timeout"):
                if key in data:
                    setattr(cfg, key, data[key])

        # Env vars override file
        for key, env_var in [
            ("credentials", "RULE34_CREDENTIALS"),
            ("user_id", "RULE34_USER_ID"),
            ("api_key", "RULE34_API_KEY"),
            ("delay", "RULE34_DELAY"),
            ("download_dir", "RULE34_DOWNLOAD_DIR"),
            ("timeout", "RULE34_TIMEOUT"),
        ]:
            val = os.environ.get(env_var)
            if val:
                if key in ("delay", "timeout"):
                    setattr(cfg, key, float(val))
                else:
                    setattr(cfg, key, val)

        # Parse credentials into user_id/api_key
        cfg._parse_credentials()
        return cfg

    def _parse_credentials(self):
        """Extract api_key and user_id from the credentials string."""
        if self.credentials:
            import urllib.parse
            params = urllib.parse.parse_qsl(self.credentials.lstrip("&"))
            parsed = dict(params)
            self.api_key = parsed.get("api_key", "")
            self.user_id = parsed.get("user_id", "")

    def save(self, path: Path | None = None):
        """Save config to file (stores credentials as-is)."""
        if path is None:
            path = DEFAULT_CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(
                {
                    "credentials": self.credentials,
                    "delay": self.delay,
                    "download_dir": self.download_dir,
                    "timeout": self.timeout,
                },
                f,
                default_flow_style=False,
            )

    def save_credentials(self, credentials: str, path: Path | None = None):
        """Save the raw credentials string and re-parse into user_id/api_key."""
        self.credentials = credentials
        self._parse_credentials()
        self.save(path)
