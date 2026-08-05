"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings."""

    base_dir: Path
    website_url: str
    ntfy_topic: str
    ntfy_server: str
    ntfy_token: str
    timezone: ZoneInfo
    check_interval: int
    heartbeat_interval: int
    urgent_interval: int
    log_level: str
    scraper_timeout: int
    max_retries: int
    enable_screenshot: bool
    enable_playwright: bool
    enable_daily_summary: bool
    daily_summary_hour: int
    log_retention_days: int

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> Settings:
        root = (base_dir or Path.cwd()).resolve()
        load_dotenv(root / ".env")
        timezone_name = os.getenv("TIMEZONE", "Asia/Kolkata").strip()
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"Unknown TIMEZONE: {timezone_name}") from exc
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LOG_LEVEL is not valid")
        server = os.getenv("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")
        if not server.startswith(("https://", "http://")):
            raise ConfigurationError("NTFY_SERVER must be an HTTP(S) URL")
        return cls(
            base_dir=root,
            website_url="https://www.jlptchennaiindia.com/",
            ntfy_topic=os.getenv("NTFY_TOPIC", "").strip(),
            ntfy_server=server,
            ntfy_token=os.getenv("NTFY_TOKEN", "").strip(),
            timezone=timezone,
            check_interval=_integer("CHECK_INTERVAL", 300, 30, 86400),
            heartbeat_interval=_integer("HEARTBEAT_INTERVAL", 3600, 60, 604800),
            urgent_interval=_integer("URGENT_INTERVAL", 600, 60, 86400),
            log_level=log_level,
            scraper_timeout=_integer("SCRAPER_TIMEOUT", 30, 5, 300),
            max_retries=_integer("MAX_RETRIES", 3, 1, 10),
            enable_screenshot=_boolean("ENABLE_SCREENSHOT", True),
            enable_playwright=_boolean("ENABLE_PLAYWRIGHT", True),
            enable_daily_summary=_boolean("ENABLE_DAILY_SUMMARY", True),
            daily_summary_hour=_integer("DAILY_SUMMARY_HOUR", 20, 0, 23),
            log_retention_days=_integer("LOG_RETENTION_DAYS", 30, 1, 365),
        )
