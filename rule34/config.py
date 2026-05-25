"""Configuration management for rule34-tool.

Reads from config.yaml (gitignored) with fallback to environment variables.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "rule34-tool" / "config.yaml"


@dataclass
class Config:
    user_id: str = ""
    api_key: str = ""
    delay: float = 1.0
    download_dir: str = "./downloads"
    timeout: int = 30

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load config from file, falling back to env vars."""
        cfg = cls()

        # Try config file
        if path is None:
            path = DEFAULT_CONFIG_PATH
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            for key in ("user_id", "api_key", "delay", "download_dir", "timeout"):
                if key in data:
                    setattr(cfg, key, data[key])

        # Env vars override file
        for key, env_var in [
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

        return cfg

    def save(self, path: Path | None = None):
        """Save config to file."""
        if path is None:
            path = DEFAULT_CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(
                {
                    "user_id": self.user_id,
                    "api_key": self.api_key,
                    "delay": self.delay,
                    "download_dir": self.download_dir,
                    "timeout": self.timeout,
                },
                f,
                default_flow_style=False,
            )
