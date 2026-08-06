from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from watchtower.adapters import NotificationEvent, WebsiteAdapter
from watchtower.adapters.jlpt_chennai import JlptChennaiAdapter
from watchtower.config import Settings
from watchtower.models import WebsiteObservation
from watchtower.monitor import MonitorEngine
from watchtower.notifier import Priority
from watchtower.state import StateStore


class ExampleAdapter(WebsiteAdapter[WebsiteObservation]):
    name = "example_test"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[str] = []
        self.events: list[str] = []

    def fetch(self) -> object:
        self.calls.append("fetch")
        return {"status": "available", "count": 7}

    def parse(self, payload: object) -> tuple[WebsiteObservation, ...]:
        self.calls.append("parse")
        assert isinstance(payload, dict)
        now = datetime(2026, 8, 6, 12, tzinfo=self.settings.timezone)
        return (
            WebsiteObservation(
                target="example:inventory",
                group="example",
                label="Inventory",
                value=int(payload["count"]),
                available=payload["status"] == "available",
                values={
                    "status": str(payload["status"]),
                    "count": int(payload["count"]),
                },
                checked_at=now,
                latency_ms=25.0,
                fetch_method="example-api",
            ),
        )

    def validate(
        self, observations: tuple[WebsiteObservation, ...]
    ) -> tuple[WebsiteObservation, ...]:
        self.calls.append("validate")
        if any(int(item.current_value or 0) < 0 for item in observations):
            raise ValueError("count cannot be negative")
        return observations

    def notify(
        self, event: NotificationEvent[WebsiteObservation], notifier: Any
    ) -> None:
        self.calls.append("notify")
        self.events.append(event.kind)
        notifier.send(
            "Example website update",
            f"Current value: {event.observations[0].current_value}",
            event.priority,
        )


class FakeNotifier:
    configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, Priority]] = []

    def send(
        self,
        title: str,
        message: str,
        priority: Priority,
        *,
        tags: tuple[str, ...] = (),
    ) -> None:
        del message, tags
        self.sent.append((title, priority))


def test_adapter_contract_has_only_four_required_operations() -> None:
    assert WebsiteAdapter.__abstractmethods__ == {
        "fetch",
        "parse",
        "validate",
        "notify",
    }


def test_generic_adapter_runs_without_jlpt_engine_changes(settings: Settings) -> None:
    configured = replace(settings, adapter="example_test")
    adapter = ExampleAdapter(configured)
    notifier = FakeNotifier()
    result = MonitorEngine(
        configured,
        adapter=adapter,
        notifier=notifier,  # type: ignore[arg-type]
        store=StateStore(configured.state_path),
    ).run_once()

    assert adapter.calls[:3] == ["fetch", "parse", "validate"]
    assert adapter.events == ["urgent", "heartbeat"]
    assert result.observation.target_key == "example:inventory"
    assert result.notifications == ("urgent", "heartbeat")
    state = StateStore(configured.state_path).load()
    assert state["targets"]["example:inventory"]["current"]["value"] == 7
    assert state["history"]["executions"][0]["observations"][0]["target"] == (
        "example:inventory"
    )

    repeated_adapter = ExampleAdapter(configured)
    repeated = MonitorEngine(
        configured,
        adapter=repeated_adapter,
        notifier=notifier,  # type: ignore[arg-type]
        store=StateStore(configured.state_path),
    ).run_once()
    assert repeated.notifications == ()
    assert repeated_adapter.events == []


def test_adapter_factory_defaults_and_rejects_unknown(settings: Settings) -> None:
    assert isinstance(WebsiteAdapter.create(settings), JlptChennaiAdapter)
    with pytest.raises(ValueError, match="Unknown website adapter"):
        WebsiteAdapter.create(replace(settings, adapter="missing"))


def test_legacy_module_paths_alias_canonical_modules() -> None:
    import jlpt_seat_watcher.monitor as legacy_monitor
    import watchtower.monitor as canonical_monitor

    assert legacy_monitor is canonical_monitor
    assert legacy_monitor.MonitorService is canonical_monitor.MonitorService
