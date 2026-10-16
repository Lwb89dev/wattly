"""Application configuration.

Settings precedence: environment variables > config file > defaults.
User preferences (theme, currency, OCR toggle, ...) are stored in the
``settings`` table at runtime; this module only holds bootstrap values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Bootstrap configuration for the app factory."""

    data_dir: Path = field(default_factory=Path.cwd)
    db_path: Path | None = None
    secret_key: str = "wattly-dev-secret"
    max_upload_mb: int = 25
    ocr_enabled: bool = True
    debug: bool = False

    @property
    def database_url(self) -> str:
        path = self.db_path or (Path(self.data_dir) / "wattly.db")
        return f"sqlite:///{path}"

    @property
    def documents_dir(self) -> Path:
        return Path(self.data_dir) / "documents"

    @property
    def max_content_length(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def default_data_dir() -> Path:
    """Resolve the default data directory (override with WATTLY_DATA_DIR)."""
    override = os.environ.get("WATTLY_DATA_DIR")
    if override:
        return Path(override)
    try:
        from platformdirs import user_data_dir

        return Path(user_data_dir("wattly", "wattly"))
    except Exception:
        return Path.home() / ".wattly"


def load_config() -> Config:
    """Build the runtime config from defaults + environment."""
    cfg = Config(data_dir=default_data_dir())
    cfg.debug = os.environ.get("WATTLY_DEBUG", "").lower() in {"1", "true", "yes"}
    cfg.secret_key = os.environ.get("WATTLY_SECRET", cfg.secret_key)
    cfg.ocr_enabled = os.environ.get("WATTLY_OCR", "1").lower() not in {"0", "false", "no"}
    if os.environ.get("WATTLY_DB"):
        cfg.db_path = Path(os.environ["WATTLY_DB"])
    return cfg
