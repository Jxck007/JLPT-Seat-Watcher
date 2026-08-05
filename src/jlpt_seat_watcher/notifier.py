"""ntfy notification provider."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import IntEnum
from urllib.parse import quote

import requests

from jlpt_seat_watcher.config import Settings

LOGGER = logging.getLogger(__name__)


class NotificationError(RuntimeError):
    """Raised when ntfy delivery is unsuccessful after retries."""


class Priority(IntEnum):
    SILENT = 1
    NORMAL = 3
    HIGH = 4
    EMERGENCY = 5


class NtfyNotifier:
    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
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
