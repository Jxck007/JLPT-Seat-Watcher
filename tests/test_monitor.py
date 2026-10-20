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


def test_every_fifteen_minutes_uses_min_and_hourly_default_replaces_it(
    settings: Settings,
) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = DetailedNotifier()

    notifications = [
        MonitorService(
            settings,
            scraper=FakeScraper(observation(now + timedelta(minutes=offset), 0)),  # type: ignore[arg-type]
            notifier=notifier,  # type: ignore[arg-type]
            store=StateStore(settings.state_path),
        )
        .run_once()
        .notifications
        for offset in (0, 15, 30, 45, 60)
    ]

    assert notifications == [("min",), ("min",), ("min",), ("min",), ("default",)]
    assert [item[2] for item in notifier.sent] == [
        Priority.MIN,
        Priority.MIN,
        Priority.MIN,
        Priority.MIN,
        Priority.DEFAULT,
    ]
    assert notifier.sent[-1][0] == "JLPT N4 — Still Monitoring"
    assert notifier.sent[-1][3] == ("white_check_mark", "clock1")
    state = StateStore(settings.state_path).load()
    assert (
        state["notifications"]["last_min_notification_at"]
        == (now + timedelta(minutes=45)).isoformat()
    )
    assert (
        state["notifications"]["last_default_notification_at"]
        == (now + timedelta(hours=1)).isoformat()
    )
    assert len(state["history"]["executions"]) == 5
    assert state["history"]["executions"][0]["notification_count"] == 1
    assert (settings.data_dir / "history.json").exists()
    assert (settings.data_dir / "history.csv").exists()


def test_state_restoration_does_not_duplicate_same_check(settings: Settings) -> None:
    now = datetime(2026, 8, 7, 0, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    assert service(settings, now, 0, notifier).run_once().notifications == ("min",)
    assert service(settings, now, 0, notifier).run_once().notifications == ()
    assert service(
        settings, now + timedelta(minutes=15), 0, notifier
    ).run_once().notifications == ("min",)
    assert [priority for _, priority in notifier.sent] == [Priority.MIN, Priority.MIN]


def test_high_overrides_lower_notifications_on_positive_changes(
    settings: Settings,
) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    first = service(settings, now, 0, notifier).run_once()
    assert first.notifications == ("min",)
    opened = service(settings, now + timedelta(minutes=15), 3, notifier).run_once()
    assert opened.notifications == ("high",)
    unchanged = service(settings, now + timedelta(minutes=30), 3, notifier).run_once()
    assert unchanged.notifications == ("min",)
    changed = service(settings, now + timedelta(minutes=45), 2, notifier).run_once()
    assert changed.notifications == ("high",)
    assert [priority for _, priority in notifier.sent] == [1, 4, 1, 4]


def test_six_hours_positive_uses_max_and_repeats_only_every_six_hours(
    settings: Settings,
) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = FakeNotifier()

    assert service(settings, now, 5, notifier).run_once().notifications == ("high",)
    before = service(
        settings, now + timedelta(hours=5, minutes=45), 5, notifier
    ).run_once()
    assert before.notifications == ("default",)
    first_max = service(settings, now + timedelta(hours=6), 5, notifier).run_once()
    assert first_max.notifications == ("max",)
    assert service(
        settings, now + timedelta(hours=6, minutes=15), 5, notifier
    ).run_once().notifications != ("max",)
    second_max = service(settings, now + timedelta(hours=12), 5, notifier).run_once()
    assert second_max.notifications == ("max",)
    assert [priority for _, priority in notifier.sent].count(Priority.MAX) == 2


def test_return_to_zero_resets_max_timer_and_new_availability_starts_again(
    settings: Settings,
) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    notifier = FakeNotifier()
    assert service(settings, now, 4, notifier).run_once().notifications == ("high",)
    assert service(
        settings, now + timedelta(hours=6), 4, notifier
    ).run_once().notifications == ("max",)
    service(settings, now + timedelta(hours=6, minutes=15), 0, notifier).run_once()
    reset_state = StateStore(settings.state_path).load()["notifications"]
    assert reset_state["availability_started_at"] is None
    assert reset_state["last_max_alert_at"] is None

    reopened_at = now + timedelta(hours=7)
    assert service(settings, reopened_at, 4, notifier).run_once().notifications == (
        "high",
    )
    restarted = StateStore(settings.state_path).load()["notifications"]
    assert restarted["availability_started_at"] == reopened_at.isoformat()
    assert service(
        settings, reopened_at + timedelta(hours=6), 4, notifier
    ).run_once().notifications == ("max",)


def test_failed_notification_remains_due(settings: Settings) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    failing = FakeNotifier(fail=True)
    assert service(settings, now, 0, failing).run_once().notifications == ()
    working = FakeNotifier()
    result = service(settings, now + timedelta(minutes=15), 0, working).run_once()
    assert result.notifications == ("min",)
    failures = StateStore(settings.state_path).load()["notifications"]["failures"]
    assert failures["count"] == 1
    assert failures["last_kind"] == "min"


def test_failed_high_and_max_alerts_remain_retryable(settings: Settings) -> None:
    now = datetime(2026, 8, 5, 10, tzinfo=settings.timezone)
    failing = FakeNotifier(fail=True)
    working = FakeNotifier()

    assert service(settings, now, 3, failing).run_once().notifications == ()
    assert service(
        settings, now + timedelta(minutes=15), 3, working
    ).run_once().notifications == ("high",)

    assert (
        service(settings, now + timedelta(hours=6, minutes=15), 3, failing)
        .run_once()
        .notifications
        == ()
    )
    assert service(
        settings, now + timedelta(hours=6, minutes=30), 3, working
    ).run_once().notifications == ("max",)


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
    assert state["notifications"]["last_min_notification_at"] is None


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
    assert first == ("high:N4",)
    assert run(now + timedelta(minutes=5), 3, 2) == ("high:N2",)
    urgent_messages = [
        message for _, message, priority in notifier.sent if priority == 4
    ]
    assert len(urgent_messages) == 2
    for message in urgent_messages:
        for expected in ("Remaining:", "Applied:", "REGISTER NOW"):
            assert expected in message

    changed = run(now + timedelta(minutes=15), 1, 2)
    assert changed == ("high:N4",)
    state = StateStore(configured.state_path).load()
    assert state["levels"]["N4"]["notifications"]["last_high_alert_remaining"] == 1
    assert state["levels"]["N2"]["notifications"]["last_high_alert_remaining"] == 2


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
    assert "high" not in result.notifications
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

    assert run(now, 1, 2) == ("high:N4:Forenoon",)
    assert run(now + timedelta(minutes=5), 1, 2) == ("high:N4:Afternoon",)
    assert run(now + timedelta(minutes=15), 1, 3) == ("high:N4:Afternoon",)

    state = StateStore(configured.state_path).load()
    assert state["targets"]["N4:Forenoon"]["current"]["remaining"] == 1
    assert state["targets"]["N4:Afternoon"]["current"]["remaining"] == 3
    assert state["levels"]["N4"]["current"]["session"] == "Forenoon"
