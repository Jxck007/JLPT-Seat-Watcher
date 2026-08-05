"""State comparison, statistics, and notification orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from jlpt_seat_watcher.config import Settings
from jlpt_seat_watcher.models import CheckResult, SeatObservation
from jlpt_seat_watcher.notifier import NotificationError, NtfyNotifier, Priority
from jlpt_seat_watcher.scraper import Scraper
from jlpt_seat_watcher.state import StateStore

LOGGER = logging.getLogger(__name__)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _is_due(last: object, now: datetime, seconds: int) -> bool:
    parsed = _parse_time(last)
    return parsed is None or now - parsed >= timedelta(seconds=seconds)


class MonitorService:
    def __init__(
        self,
        settings: Settings,
        *,
        scraper: Scraper | None = None,
        notifier: NtfyNotifier | None = None,
        store: StateStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.scraper = scraper or Scraper(settings)
        self.notifier = notifier or NtfyNotifier(settings)
        self.store = store or StateStore(settings.state_path)
        self.clock = clock or (lambda: datetime.now(settings.timezone))

    def _send(
        self,
        sent: list[str],
        kind: str,
        title: str,
        body: str,
        priority: Priority,
        tags: tuple[str, ...],
    ) -> bool:
        if not self.notifier.configured:
            LOGGER.warning("Notification skipped because NTFY_TOPIC is not configured")
            return False
        try:
            self.notifier.send(title, body, priority, tags=tags)
            sent.append(kind)
            return True
        except NotificationError:
            LOGGER.exception("Notification failed", extra={"notification_type": kind})
            return False

    def _record_failure(self, now: datetime) -> None:
        with self.store.transaction() as state:
            stats = state["statistics"]
            stats["checks_total"] += 1
            stats["failures"] += 1
            stats["consecutive_failures"] += 1
            stats["last_failure_at"] = now.isoformat()

    @staticmethod
    def _changed(previous: dict[str, Any] | None, observation: SeatObservation) -> bool:
        if previous is None:
            return False
        return any(
            int(previous[key]) != value
            for key, value in (
                ("total", observation.total),
                ("applied", observation.applied),
                ("remaining", observation.remaining),
            )
        )

    @staticmethod
    def _update_statistics(
        state: dict[str, Any], observation: SeatObservation, today: date
    ) -> None:
        stats = state["statistics"]
        stats["checks_total"] += 1
        stats["successes"] += 1
        stats["consecutive_failures"] = 0
        stats["latency_total_ms"] += observation.latency_ms
        stats["last_success_at"] = observation.checked_at.isoformat()
        daily = stats["daily"]
        if daily["date"] != today.isoformat():
            daily.update(
                {
                    "date": today.isoformat(),
                    "checks": 0,
                    "min_remaining": None,
                    "max_remaining": None,
                    "duration_total_ms": 0.0,
                    "latency_total_ms": 0.0,
                }
            )
        daily["checks"] += 1
        daily["latency_total_ms"] += observation.latency_ms
        remaining = observation.remaining
        daily["min_remaining"] = (
            remaining
            if daily["min_remaining"] is None
            else min(int(daily["min_remaining"]), remaining)
        )
        daily["max_remaining"] = (
            remaining
            if daily["max_remaining"] is None
            else max(int(daily["max_remaining"]), remaining)
        )

    def run_once(self) -> CheckResult:
        started = time.monotonic()
        try:
            observation = self.scraper.fetch()
        except Exception:
            self._record_failure(self.clock())
            LOGGER.exception("Seat check failed")
            raise
        now = observation.checked_at
        sent: list[str] = []
        with self.store.transaction() as state:
            previous = state.get("current")
            changed = self._changed(previous, observation)
            state["previous"] = previous
            state["current"] = observation.to_dict()
            self._update_statistics(state, observation, now.date())
            notifications = state["notifications"]

            urgent_changed = (
                previous is not None
                and int(previous["remaining"]) != observation.remaining
            )
            urgent_due = _is_due(
                notifications["last_urgent_at"], now, self.settings.urgent_interval
            )
            if observation.remaining > 0 and (urgent_changed or urgent_due):
                body = (
                    f"Remaining: {observation.remaining}\n"
                    f"Applied: {observation.applied}\n"
                    f"Total: {observation.total}\n"
                    f"Website: {self.settings.website_url}\n"
                    f"Checked: {now.isoformat()}"
                )
                if self._send(
                    sent,
                    "urgent",
                    "🚨 JLPT N4 SEATS AVAILABLE",
                    body,
                    Priority.HIGH,
                    ("rotating_light", "jlpt"),
                ):
                    notifications["last_urgent_at"] = now.isoformat()
                    notifications["last_urgent_remaining"] = observation.remaining

            if _is_due(
                notifications["last_heartbeat_at"],
                now,
                self.settings.heartbeat_interval,
            ):
                body = (
                    f"Remaining Seats: {observation.remaining}\n"
                    f"Checked: {now.isoformat()}"
                )
                if self._send(
                    sent,
                    "heartbeat",
                    "✅ JLPT Monitor Running",
                    body,
                    Priority.SILENT,
                    ("white_check_mark", "jlpt"),
                ):
                    notifications["last_heartbeat_at"] = now.isoformat()

            daily_due = (
                self.settings.enable_daily_summary
                and now.hour >= self.settings.daily_summary_hour
                and notifications["last_daily_summary_date"] != now.date().isoformat()
            )
            if daily_due:
                daily = state["statistics"]["daily"]
                checks = max(int(daily["checks"]), 1)
                body = (
                    f"Checks today: {daily['checks']}\n"
                    f"Remaining now: {observation.remaining}\n"
                    f"Range: {daily['min_remaining']}-{daily['max_remaining']}\n"
                    f"Average website latency: "
                    f"{daily['latency_total_ms'] / checks:.0f} ms\n"
                    f"Last successful check: {now.isoformat()}"
                )
                if self._send(
                    sent,
                    "daily_summary",
                    "JLPT Monitor Daily Summary",
                    body,
                    Priority.NORMAL,
                    ("bar_chart", "jlpt"),
                ):
                    notifications["last_daily_summary_date"] = now.date().isoformat()

            duration_ms = (time.monotonic() - started) * 1000
            state["statistics"]["duration_total_ms"] += duration_ms
            state["statistics"]["daily"]["duration_total_ms"] += duration_ms

        LOGGER.info(
            "Seat check completed",
            extra={
                "remaining": observation.remaining,
                "applied": observation.applied,
                "total": observation.total,
                "changed": changed,
                "duration_ms": round(duration_ms, 2),
                "latency_ms": observation.latency_ms,
                "fetch_method": observation.fetch_method,
                "notifications": sent,
            },
        )
        return CheckResult(observation, changed, tuple(sent), round(duration_ms, 2))
