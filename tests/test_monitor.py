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


class RecordingNotifier:
    configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, Priority]] = []

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        del tags
        self.sent.append((title, message, priority))


class DetailedNotifier:
    configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, Priority, tuple[str, ...]]] = []

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        self.sent.append((title, message, priority, tags))


class MultiScraper:
    def __init__(self, observations: tuple[SeatObservation, ...]) -> None:
        self.observations = observations

    def fetch_all(self) -> tuple[SeatObservation, ...]:
        return self.observations


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
    settings = replace(settings, quiet_heartbeat=True, enable_daily_summary=False)
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    first = service(settings, now, 0, notifier).run_once()
    assert first.notifications == ("heartbeat",)
    second = service(settings, now + timedelta(minutes=15), 0, notifier).run_once()
    assert second.notifications == ()
    third = service(settings, now + timedelta(hours=1), 0, notifier).run_once()
    assert third.notifications == ("heartbeat",)
    state = StateStore(settings.state_path).load()
    assert len(state["history"]["executions"]) == 3
    assert state["history"]["executions"][0]["notification_count"] == 1
    assert (settings.data_dir / "history.json").exists()
    assert (settings.data_dir / "history.csv").exists()


def test_ordinary_zero_check_is_silent_before_hourly_heartbeat(
    settings: Settings,
) -> None:
    configured = replace(settings, quiet_heartbeat=True, enable_daily_summary=False)
    now = datetime(2026, 8, 7, 0, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    service(configured, now, 0, notifier).run_once()
    result = service(configured, now + timedelta(minutes=15), 0, notifier).run_once()
    assert result.notifications == ()


def test_heartbeat_survives_restart_and_uses_low_priority(
    settings: Settings,
) -> None:
    configured = replace(settings, quiet_heartbeat=True, enable_daily_summary=False)
    now = datetime(2026, 8, 7, 0, tzinfo=settings.timezone)
    notifier = DetailedNotifier()
    first = MonitorService(
        configured,
        scraper=FakeScraper(observation(now, 0)),  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        store=StateStore(configured.state_path),
    ).run_once()
    restarted = MonitorService(
        configured,
        scraper=FakeScraper(observation(now + timedelta(minutes=15), 0)),  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        store=StateStore(configured.state_path),
    ).run_once()

    assert first.notifications == ("heartbeat",)
    assert restarted.notifications == ()
    assert notifier.sent[0][0] == "JLPT N4 Monitor Active"
    assert notifier.sent[0][2] == Priority.LOW == 2
    assert notifier.sent[0][3] == ("white_check_mark", "clock1")
    assert "Remaining: 0" in notifier.sent[0][1]
    assert "Applied: 850 / 850" in notifier.sent[0][1]


def test_positive_alerts_immediately_on_change_then_every_fifteen_minutes(
    settings: Settings,
) -> None:
    settings = replace(
        settings,
        quiet_heartbeat=True,
        enable_daily_summary=False,
        available_alert_interval=900,
        repeat_available_alerts=True,
    )
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    first = service(settings, now, 0, notifier).run_once()
    assert first.notifications == ("heartbeat",)
    opened = service(settings, now + timedelta(minutes=5), 3, notifier).run_once()
    assert opened.notifications == ("urgent",)
    quiet = service(settings, now + timedelta(minutes=9), 3, notifier).run_once()
    assert quiet.notifications == ()
    repeat = service(settings, now + timedelta(minutes=20), 3, notifier).run_once()
    assert repeat.notifications == ("urgent",)
    changed = service(settings, now + timedelta(minutes=21), 2, notifier).run_once()
    assert changed.notifications == ("urgent",)
    closed = service(settings, now + timedelta(minutes=36), 0, notifier).run_once()
    assert "urgent" not in closed.notifications


def test_daily_summary_once(settings: Settings) -> None:
    now = datetime(2026, 8, 5, 20, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    first = service(settings, now, 0, notifier).run_once()
    assert set(first.notifications) == {"heartbeat", "daily_summary"}
    second = service(settings, now + timedelta(minutes=5), 0, notifier).run_once()
    assert second.notifications == ()


def test_failed_notification_remains_due(settings: Settings) -> None:
    settings = replace(settings, quiet_heartbeat=True, enable_daily_summary=False)
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    failing = FakeNotifier(fail=True)
    assert service(settings, now, 0, failing).run_once().notifications == ()
    working = FakeNotifier()
    result = service(settings, now + timedelta(minutes=15), 0, working).run_once()
    assert result.notifications == ("heartbeat",)
    failures = StateStore(settings.state_path).load()["notifications"]["failures"]
    assert failures["count"] == 1
    assert failures["last_kind"] == "heartbeat"


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


def multi_observation(
    now: datetime, level: str, session: str, remaining: int
) -> SeatObservation:
    total = 500
    return SeatObservation(
        session,
        level,
        total,
        total - remaining,
        remaining,
        now,
        140.0,
        "requests",
    )


def test_multi_level_alerts_include_required_fields_and_deduplicate(
    settings: Settings,
) -> None:
    configured = replace(settings, watched_levels=("N4", "N2"))
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = RecordingNotifier()

    def run(at: datetime, n4: int, n2: int) -> tuple[str, ...]:
        observations = (
            multi_observation(at, "N4", "Afternoon", n4),
            multi_observation(at, "N2", "Forenoon", n2),
        )
        return (
            MonitorService(
                configured,
                scraper=MultiScraper(observations),  # type: ignore[arg-type]
                notifier=notifier,  # type: ignore[arg-type]
                store=StateStore(configured.state_path),
            )
            .run_once()
            .notifications
        )

    first = run(now, 3, 2)
    assert first == ("urgent:N4", "urgent:N2", "heartbeat")
    urgent_messages = [
        message for _, message, priority in notifier.sent if priority == 4
    ]
    assert len(urgent_messages) == 2
    for message in urgent_messages:
        for expected in ("Remaining:", "Applied:", "Register immediately."):
            assert expected in message

    assert run(now + timedelta(minutes=5), 3, 2) == ()
    changed = run(now + timedelta(minutes=6), 1, 2)
    assert changed == ("urgent:N4",)
    state = StateStore(configured.state_path).load()
    assert state["levels"]["N4"]["notifications"]["last_urgent_remaining"] == 1
    assert state["levels"]["N2"]["notifications"]["last_urgent_remaining"] == 2


def test_legacy_n4_state_migrates_without_duplicate_alert(settings: Settings) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    store = StateStore(settings.state_path)
    state = store.load()
    state["current"] = observation(now, 4).to_dict()
    state["notifications"]["last_urgent_at"] = now.isoformat()
    state["notifications"]["last_urgent_remaining"] = 4
    store.save(state)
    notifier = FakeNotifier()
    result = service(settings, now + timedelta(minutes=5), 4, notifier).run_once()
    assert "urgent" not in result.notifications
    assert store.load()["levels"]["N4"]["current"]["remaining"] == 4


def test_both_sessions_have_independent_alert_state(settings: Settings) -> None:
    configured = replace(settings, watched_levels=("N4",), session_mode="Both")
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = RecordingNotifier()

    def run(at: datetime, forenoon: int, afternoon: int) -> tuple[str, ...]:
        observations = (
            multi_observation(at, "N4", "Forenoon", forenoon),
            multi_observation(at, "N4", "Afternoon", afternoon),
        )
        return (
            MonitorService(
                configured,
                scraper=MultiScraper(observations),  # type: ignore[arg-type]
                notifier=notifier,  # type: ignore[arg-type]
                store=StateStore(configured.state_path),
            )
            .run_once()
            .notifications
        )

    assert run(now, 1, 2) == (
        "urgent:N4:Forenoon",
        "urgent:N4:Afternoon",
        "heartbeat",
    )
    assert run(now + timedelta(minutes=5), 1, 2) == ()
    assert run(now + timedelta(minutes=6), 1, 3) == ("urgent:N4:Afternoon",)

    state = StateStore(configured.state_path).load()
    assert state["targets"]["N4:Forenoon"]["current"]["remaining"] == 1
    assert state["targets"]["N4:Afternoon"]["current"]["remaining"] == 3
    assert state["levels"]["N4"]["current"]["session"] == "Forenoon"
