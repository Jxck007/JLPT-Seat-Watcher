"""YAML-backed application configuration with environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when YAML or environment configuration is invalid."""


SUPPORTED_LEVELS = ("N5", "N4", "N3", "N2", "N1")
SUPPORTED_SESSION_MODES = ("Auto", "Forenoon", "Afternoon", "Both")


def _configured(config: dict[str, object], name: str, default: object) -> object:
    if name in os.environ:
        return os.environ[name]
    return config.get(name.lower(), default)


def _boolean(config: dict[str, object], name: str, default: bool) -> bool:
    raw = _configured(config, name, default)
    if isinstance(raw, bool):
        return raw
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _integer(
    config: dict[str, object], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = _configured(config, name, default)
    try:
        value = int(str(raw))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _load_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read {path.name}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise ConfigurationError(f"{path.name} must contain a YAML mapping")
    return loaded


def _watched_levels(config: dict[str, object]) -> tuple[str, ...]:
    raw: object = config.get("watched_levels", ["N4"])
    env_value = os.getenv("WATCHED_LEVELS")
    if env_value is not None:
        raw = [item.strip() for item in env_value.split(",")]
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ConfigurationError("watched_levels must be a non-empty YAML list")
    levels = tuple(str(item).strip().upper() for item in raw)
    if any(level not in SUPPORTED_LEVELS for level in levels):
        supported = ", ".join(SUPPORTED_LEVELS)
        raise ConfigurationError(f"watched_levels may only contain: {supported}")
    if len(set(levels)) != len(levels):
        raise ConfigurationError("watched_levels cannot contain duplicates")
    return levels


def _session_mode(config: dict[str, object]) -> str:
    raw = os.getenv("WATCHED_SESSION", config.get("session", "Auto"))
    normalized = str(raw).strip().casefold()
    modes = {mode.casefold(): mode for mode in SUPPORTED_SESSION_MODES}
    if normalized not in modes:
        supported = ", ".join(SUPPORTED_SESSION_MODES)
        raise ConfigurationError(f"session must be one of: {supported}")
    return modes[normalized]


def _string_list(config: dict[str, object], key: str, env_name: str) -> tuple[str, ...]:
    raw: object = config.get(key, [])
    env_value = os.getenv(env_name)
    if env_value is not None:
        raw = env_value.split(",")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ConfigurationError(f"{key} must be a YAML list or comma-separated value")
    return tuple(str(item).strip() for item in raw if str(item).strip())


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
    watched_levels: tuple[str, ...] = ("N4",)
    session_mode: str = "Auto"
    notification_provider: str = "ntfy"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: tuple[str, ...] = ()
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    history_retention_days: int = 30
    adapter: str = "jlpt_chennai"

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
        config = _load_yaml(root / "config.yaml")
        timezone_name = str(_configured(config, "TIMEZONE", "Asia/Kolkata")).strip()
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"Unknown TIMEZONE: {timezone_name}") from exc
        log_level = str(_configured(config, "LOG_LEVEL", "INFO")).strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LOG_LEVEL is not valid")
        server = (
            str(_configured(config, "NTFY_SERVER", "https://ntfy.sh"))
            .strip()
            .rstrip("/")
        )
        if not server.startswith(("https://", "http://")):
            raise ConfigurationError("NTFY_SERVER must be an HTTP(S) URL")
        website_url = str(
            _configured(config, "WEBSITE_URL", "https://www.jlptchennaiindia.com/")
        ).strip()
        if not website_url.startswith(("https://", "http://")):
            raise ConfigurationError("WEBSITE_URL must be an HTTP(S) URL")
        smtp_use_tls = _boolean(config, "SMTP_USE_TLS", True)
        smtp_use_ssl = _boolean(config, "SMTP_USE_SSL", False)
        if smtp_use_tls and smtp_use_ssl:
            raise ConfigurationError(
                "smtp_use_tls and smtp_use_ssl cannot both be true"
            )
        notification_provider = (
            str(_configured(config, "NOTIFICATION_PROVIDER", "ntfy")).strip().casefold()
        )
        if not notification_provider:
            raise ConfigurationError("notification_provider cannot be empty")
        adapter = str(
            os.getenv("WATCHTOWER_ADAPTER", config.get("adapter", "jlpt_chennai"))
        )
        adapter = adapter.strip().casefold()
        if not adapter:
            raise ConfigurationError("adapter cannot be empty")
        return cls(
            base_dir=root,
            website_url=website_url,
            ntfy_topic=os.getenv("NTFY_TOPIC", "").strip(),
            ntfy_server=server,
            ntfy_token=os.getenv("NTFY_TOKEN", "").strip(),
            timezone=timezone,
            check_interval=_integer(config, "CHECK_INTERVAL", 300, 30, 86400),
            heartbeat_interval=_integer(config, "HEARTBEAT_INTERVAL", 3600, 60, 604800),
            urgent_interval=_integer(config, "URGENT_INTERVAL", 600, 60, 86400),
            log_level=log_level,
            scraper_timeout=_integer(config, "SCRAPER_TIMEOUT", 30, 5, 300),
            max_retries=_integer(config, "MAX_RETRIES", 3, 1, 10),
            enable_screenshot=_boolean(config, "ENABLE_SCREENSHOT", True),
            enable_playwright=_boolean(config, "ENABLE_PLAYWRIGHT", True),
            enable_daily_summary=_boolean(config, "ENABLE_DAILY_SUMMARY", True),
            daily_summary_hour=_integer(config, "DAILY_SUMMARY_HOUR", 20, 0, 23),
            log_retention_days=_integer(config, "LOG_RETENTION_DAYS", 30, 1, 365),
            history_retention_days=_integer(
                config, "HISTORY_RETENTION_DAYS", 30, 1, 365
            ),
            adapter=adapter,
            watched_levels=_watched_levels(config),
            session_mode=_session_mode(config),
            notification_provider=notification_provider,
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", "").strip(),
            smtp_host=str(_configured(config, "SMTP_HOST", "")).strip(),
            smtp_port=_integer(config, "SMTP_PORT", 587, 1, 65535),
            smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
            smtp_from=str(_configured(config, "SMTP_FROM", "")).strip(),
            smtp_to=_string_list(config, "smtp_to", "SMTP_TO"),
            smtp_use_tls=smtp_use_tls,
            smtp_use_ssl=smtp_use_ssl,
        )
