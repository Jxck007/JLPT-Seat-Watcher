from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest

from jlpt_seat_watcher.config import Settings
from jlpt_seat_watcher.models import SeatObservation
from jlpt_seat_watcher.monitor import MonitorService
from jlpt_seat_watcher.notifier import NotificationError, Priority
from jlpt_seat_watcher.state import StateStore


class FakeScraper:
    def __init__(self, observation: SeatObservation) -> None:
        self.observation = observation

    def fetch(self) -> SeatObservation:
        return self.observation


class FailingScraper:
    def fetch(self) -> SeatObservation:
        raise RuntimeError("offline")


class FakeNotifier:
    configured = True

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, Priority]] = []
        self.fail = fail

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        del message, tags
        if self.fail:
            raise NotificationError("failed")
        self.sent.append((title, priority))


def observation(now: datetime, remaining: int = 0) -> SeatObservation:
    return SeatObservation(
        "Afternoon",
        "N4",
        850,
        850 - remaining,
        remaining,
        now,
        120.0,
        "requests",
    )


def service(
    settings: Settings,
    now: datetime,
    remaining: int,
    notifier: FakeNotifier,
) -> MonitorService:
    return MonitorService(
        settings,
        scraper=FakeScraper(observation(now, remaining)),  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        store=StateStore(settings.state_path),
        clock=lambda: now,
    )


def test_first_zero_sends_heartbeat_and_deduplicates(settings: Settings) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    first = service(settings, now, 0, notifier).run_once()
    assert first.notifications == ("heartbeat",)
    second = service(settings, now + timedelta(minutes=5), 0, notifier).run_once()
    assert second.notifications == ()
    third = service(settings, now + timedelta(hours=1), 0, notifier).run_once()
    assert third.notifications == ("heartbeat",)


def test_positive_alerts_immediately_on_change_then_every_ten_minutes(
    settings: Settings,
) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    first = service(settings, now, 0, notifier).run_once()
    assert "heartbeat" in first.notifications
    opened = service(settings, now + timedelta(minutes=5), 3, notifier).run_once()
    assert opened.notifications == ("urgent",)
    quiet = service(settings, now + timedelta(minutes=9), 3, notifier).run_once()
    assert quiet.notifications == ()
    repeat = service(settings, now + timedelta(minutes=15), 3, notifier).run_once()
    assert repeat.notifications == ("urgent",)
    changed = service(settings, now + timedelta(minutes=16), 2, notifier).run_once()
    assert changed.notifications == ("urgent",)
    closed = service(settings, now + timedelta(minutes=30), 0, notifier).run_once()
    assert "urgent" not in closed.notifications


def test_daily_summary_once(settings: Settings) -> None:
    now = datetime(2026, 8, 5, 20, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    first = service(settings, now, 0, notifier).run_once()
    assert set(first.notifications) == {"heartbeat", "daily_summary"}
    second = service(settings, now + timedelta(minutes=5), 0, notifier).run_once()
    assert second.notifications == ()


def test_failed_notification_remains_due(settings: Settings) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    failing = FakeNotifier(fail=True)
    assert service(settings, now, 5, failing).run_once().notifications == ()
    working = FakeNotifier()
    result = service(settings, now + timedelta(minutes=5), 5, working).run_once()
    assert set(result.notifications) == {"urgent", "heartbeat"}


def test_scrape_failure_updates_failure_statistics(settings: Settings) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    monitor = MonitorService(
        settings,
        scraper=FailingScraper(),  # type: ignore[arg-type]
        notifier=FakeNotifier(),  # type: ignore[arg-type]
        store=StateStore(settings.state_path),
        clock=lambda: now,
    )
    with pytest.raises(RuntimeError, match="offline"):
        monitor.run_once()
    stats: dict[str, Any] = StateStore(settings.state_path).load()["statistics"]
    assert stats["failures"] == 1
    assert stats["consecutive_failures"] == 1


def test_no_topic_does_not_mark_notifications_sent(settings: Settings) -> None:
    no_topic = replace(settings, ntfy_topic="")
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    result = MonitorService(
        no_topic,
        scraper=FakeScraper(observation(now)),  # type: ignore[arg-type]
        store=StateStore(no_topic.state_path),
    ).run_once()
    assert result.notifications == ()
    state = StateStore(no_topic.state_path).load()
    assert state["notifications"]["last_heartbeat_at"] is None
