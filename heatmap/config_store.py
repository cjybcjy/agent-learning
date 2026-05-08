import os
from pathlib import Path

import yaml


class ConfigStore:
    """Store user-configurable secrets (API keys) in a local file."""

    def __init__(self, path: Path):
        self._path = path
        self._data: dict = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = yaml.safe_load(f) or {}
            except Exception:
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)
        # Restrict to owner-only read/write
        os.chmod(self._path, 0o600)

    def get(self, key: str, default: str | None = None) -> str | None:
        """Get config value. Fallback to environment variable."""
        env_val = os.environ.get(key)
        if env_val:
            return env_val
        return self._data.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Set config value and persist."""
        self._data[key] = value
        self._save()

    def get_masked(self) -> dict:
        """Return config with sensitive values masked for display."""
        result = {}
        for k, v in self._data.items():
            if isinstance(v, str) and len(v) > 8:
                result[k] = v[:4] + "****" + v[-4:]
            else:
                result[k] = v
        return result
