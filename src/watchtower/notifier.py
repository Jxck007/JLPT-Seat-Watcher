"""Pluggable notification providers."""

from __future__ import annotations

import logging
import smtplib
import ssl
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from email.message import EmailMessage
from enum import IntEnum
from typing import Any, ClassVar
from urllib.parse import quote

import requests

from watchtower.config import Settings

LOGGER = logging.getLogger(__name__)


class NotificationError(RuntimeError):
    """Raised when notification delivery is unsuccessful."""


class Priority(IntEnum):
    MIN = 1
    LOW = 2
    # Kept as an alias for callers using the original public name.
    SILENT = 2
    DEFAULT = 3
    NORMAL = 3
    HIGH = 4
    MAX = 5
    EMERGENCY = 5


class Notifier(ABC):
    """Self-registering base class for notification providers."""

    provider: ClassVar[str] = ""
    configuration_hint: ClassVar[str] = "selected provider"
    _providers: ClassVar[dict[str, type[Notifier]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        provider = getattr(cls, "provider", "").strip().casefold()
        if provider:
            Notifier._providers[provider] = cls

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    def create(cls, settings: Settings) -> Notifier:
        """Create the provider selected by configuration."""

        provider = settings.notification_provider.strip().casefold()
        notifier_class = cls._providers.get(provider)
        if notifier_class is None:
            available = ", ".join(sorted(cls._providers))
            raise NotificationError(
                f"Unknown notification provider '{provider}'. Available: {available}"
            )
        return notifier_class(settings)

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Return whether all required provider settings are present."""

    @abstractmethod
    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        """Deliver one notification or raise NotificationError."""


class NtfyNotifier(Notifier):
    """ntfy provider preserving the original transport behavior."""

    provider = "ntfy"
    configuration_hint = "NTFY_TOPIC"

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(settings)
        self.session = session or requests.Session()
        self.sleep = sleep

    @property
    def configured(self) -> bool:
        return bool(self.settings.ntfy_topic)

    def _endpoint(self) -> str:
        topic = self.settings.ntfy_topic
        if topic.startswith(("https://", "http://")):
            return topic
        return f"{self.settings.ntfy_server}/{quote(topic, safe='')}"

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        if not self.configured:
            raise NotificationError("NTFY_TOPIC is not configured")
        headers = {
            "Title": title,
            "Priority": str(int(priority)),
            "Click": self.settings.website_url,
        }
        if tags:
            headers["Tags"] = ",".join(tags)
        if self.settings.ntfy_token:
            headers["Authorization"] = f"Bearer {self.settings.ntfy_token}"
        last_status: int | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.session.post(
                    self._endpoint(),
                    data=message.encode("utf-8"),
                    headers=headers,
                    timeout=self.settings.scraper_timeout,
                )
                last_status = response.status_code
                response.raise_for_status()
                LOGGER.info(
                    "Notification delivered",
                    extra={"notification_title": title, "priority": int(priority)},
                )
                return
            except requests.RequestException:
                LOGGER.warning(
                    "Notification delivery attempt failed",
                    extra={"attempt": attempt, "status": last_status},
                )
                if attempt < self.settings.max_retries:
                    self.sleep(min(30.0, 2 ** (attempt - 1)))
        raise NotificationError(
            f"ntfy delivery failed after {self.settings.max_retries} attempts"
        )


class _HttpNotifier(Notifier):
    """Shared retry transport for JSON-based notification providers."""

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(settings)
        self.session = session or requests.Session()
        self.sleep = sleep

    def _post_json(self, endpoint: str, payload: dict[str, object]) -> None:
        last_status: int | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.session.post(
                    endpoint,
                    json=payload,
                    timeout=self.settings.scraper_timeout,
                )
                last_status = response.status_code
                response.raise_for_status()
                LOGGER.info(
                    "Notification delivered",
                    extra={"notification_provider": self.provider},
                )
                return
            except requests.RequestException:
                LOGGER.warning(
                    "Notification delivery attempt failed",
                    extra={
                        "provider": self.provider,
                        "attempt": attempt,
                        "status": last_status,
                    },
                )
                if attempt < self.settings.max_retries:
                    self.sleep(min(30.0, 2 ** (attempt - 1)))
        raise NotificationError(
            f"{self.provider} delivery failed after "
            f"{self.settings.max_retries} attempts"
        )


class TelegramNotifier(_HttpNotifier):
    """Telegram Bot API provider."""

    provider = "telegram"
    configuration_hint = "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"

    @property
    def configured(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        del priority, tags
        if not self.configured:
            raise NotificationError(f"{self.configuration_hint} are not configured")
        endpoint = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        self._post_json(
            endpoint,
            {
                "chat_id": self.settings.telegram_chat_id,
                "text": f"{title}\n\n{message}\n\n{self.settings.website_url}",
                "disable_web_page_preview": False,
            },
        )


class DiscordWebhookNotifier(_HttpNotifier):
    """Discord webhook provider."""

    provider = "discord"
    configuration_hint = "DISCORD_WEBHOOK_URL"

    @property
    def configured(self) -> bool:
        return bool(self.settings.discord_webhook_url)

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        del priority, tags
        if not self.configured:
            raise NotificationError(f"{self.configuration_hint} is not configured")
        self._post_json(
            self.settings.discord_webhook_url,
            {"content": f"**{title}**\n{message}\n{self.settings.website_url}"},
        )


class SlackWebhookNotifier(_HttpNotifier):
    """Slack incoming webhook provider."""

    provider = "slack"
    configuration_hint = "SLACK_WEBHOOK_URL"

    @property
    def configured(self) -> bool:
        return bool(self.settings.slack_webhook_url)

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        del priority, tags
        if not self.configured:
            raise NotificationError(f"{self.configuration_hint} is not configured")
        text = f"*{title}*\n{message}\n" f"<{self.settings.website_url}|Open website>"
        self._post_json(
            self.settings.slack_webhook_url,
            {"text": text},
        )


class EmailSmtpNotifier(Notifier):
    """SMTP email provider with optional STARTTLS or implicit TLS."""

    provider = "email"
    configuration_hint = "SMTP host, sender, and recipients"

    def __init__(
        self,
        settings: Settings,
        *,
        smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
        smtp_ssl_factory: Callable[..., smtplib.SMTP_SSL] = smtplib.SMTP_SSL,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(settings)
        self.smtp_factory = smtp_factory
        self.smtp_ssl_factory = smtp_ssl_factory
        self.sleep = sleep

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.smtp_host
            and self.settings.smtp_from
            and self.settings.smtp_to
        )

    def _message(self, title: str, message: str, priority: Priority) -> EmailMessage:
        email = EmailMessage()
        email["Subject"] = title
        email["From"] = self.settings.smtp_from
        email["To"] = ", ".join(self.settings.smtp_to)
        email["X-Priority"] = "1" if priority >= Priority.HIGH else "3"
        email.set_content(f"{message}\n\nWebsite: {self.settings.website_url}\n")
        return email

    def _client(self) -> smtplib.SMTP:
        if self.settings.smtp_use_ssl:
            return self.smtp_ssl_factory(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.scraper_timeout,
                context=ssl.create_default_context(),
            )
        return self.smtp_factory(
            self.settings.smtp_host,
            self.settings.smtp_port,
            timeout=self.settings.scraper_timeout,
        )

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        del tags
        if not self.configured:
            raise NotificationError(f"{self.configuration_hint} are not configured")
        email = self._message(title, message, priority)
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                with self._client() as client:
                    if self.settings.smtp_use_tls:
                        client.starttls(context=ssl.create_default_context())
                    if self.settings.smtp_username:
                        client.login(
                            self.settings.smtp_username,
                            self.settings.smtp_password,
                        )
                    client.send_message(email)
                LOGGER.info(
                    "Notification delivered",
                    extra={"notification_provider": self.provider},
                )
                return
            except (OSError, smtplib.SMTPException):
                LOGGER.warning(
                    "Notification delivery attempt failed",
                    extra={"provider": self.provider, "attempt": attempt},
                )
                if attempt < self.settings.max_retries:
                    self.sleep(min(30.0, 2 ** (attempt - 1)))
        raise NotificationError(
            f"email delivery failed after {self.settings.max_retries} attempts"
        )
