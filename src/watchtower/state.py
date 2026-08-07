"""Atomic, lock-protected monitor state persistence."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock


class StateError(RuntimeError):
    """Raised when state cannot be safely used."""


def new_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "previous": None,
        "current": None,
        "levels": {},
        "targets": {},
        "history": {
            "schema_version": 1,
            "retention_days": 30,
            "executions": [],
            "daily_statistics": [],
        },
        "notifications": {
            "last_min_notification_at": None,
            "last_default_notification_at": None,
            "last_high_alert_at": None,
            "last_high_alert_remaining": None,
            "availability_started_at": None,
            "last_max_alert_at": None,
            "last_status_notification_at": None,
            "notification_cadence_started_at": None,
            "last_heartbeat_at": None,
            "last_urgent_at": None,
            "last_urgent_remaining": None,
            "last_daily_summary_date": None,
            "failures": {"count": 0, "last_at": None, "last_kind": None},
        },
        "statistics": {
            "checks_total": 0,
            "successes": 0,
            "failures": 0,
            "consecutive_failures": 0,
            "duration_total_ms": 0.0,
            "latency_total_ms": 0.0,
            "last_success_at": None,
            "last_failure_at": None,
            "daily": {
                "date": None,
                "checks": 0,
                "min_remaining": None,
                "max_remaining": None,
                "duration_total_ms": 0.0,
                "latency_total_ms": 0.0,
            },
        },
    }


def _notification_defaults() -> dict[str, Any]:
    return {
        "last_min_notification_at": None,
        "last_default_notification_at": None,
        "last_high_alert_at": None,
        "last_high_alert_remaining": None,
        "availability_started_at": None,
        "last_max_alert_at": None,
        "last_status_notification_at": None,
        "notification_cadence_started_at": None,
        "last_heartbeat_at": None,
        "last_urgent_at": None,
        "last_urgent_remaining": None,
        "last_daily_summary_date": None,
        "failures": {"count": 0, "last_at": None, "last_kind": None},
    }


def _normalize_notifications(value: object) -> dict[str, Any]:
    notifications = value if isinstance(value, dict) else {}
    for key, default in _notification_defaults().items():
        notifications.setdefault(
            key, default.copy() if isinstance(default, dict) else default
        )

    # Existing installations used heartbeat/urgent names. Treat their successful
    # timestamps as cadence anchors so an upgrade cannot duplicate an alert.
    if notifications["last_default_notification_at"] is None:
        notifications["last_default_notification_at"] = notifications.get(
            "last_heartbeat_at"
        )
    if notifications["last_high_alert_at"] is None:
        notifications["last_high_alert_at"] = notifications.get("last_urgent_at")
    if notifications["last_high_alert_remaining"] is None:
        notifications["last_high_alert_remaining"] = notifications.get(
            "last_urgent_remaining"
        )
    if notifications["last_status_notification_at"] is None:
        notifications["last_status_notification_at"] = (
            notifications["last_high_alert_at"]
            or notifications["last_default_notification_at"]
        )
    if notifications["notification_cadence_started_at"] is None:
        notifications["notification_cadence_started_at"] = notifications[
            "last_status_notification_at"
        ]
    return notifications


def _normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("last_check", None)
    state["notifications"] = _normalize_notifications(state.get("notifications"))
    for collection_name in ("targets", "levels"):
        targets = state.get(collection_name)
        if not isinstance(targets, dict):
            continue
        for target in targets.values():
            if isinstance(target, dict):
                target["notifications"] = _normalize_notifications(
                    target.get("notifications")
                )
    return state


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = FileLock(str(path.with_suffix(".lock")), timeout=60)

    def _recover_corrupt(self) -> dict[str, Any]:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self.path.with_name(f"state.corrupt-{timestamp}.json")
        os.replace(self.path, destination)
        return new_state()

    def load(self, *, recover: bool = True) -> dict[str, Any]:
        if not self.path.exists():
            return new_state()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("schema_version") != 1:
                raise StateError("Unsupported or missing state schema")
            return _normalize_state(value)
        except (OSError, json.JSONDecodeError, StateError) as exc:
            if not recover:
                raise StateError(f"State is unreadable: {exc}") from exc
            return self._recover_corrupt()

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            state = self.load()
            yield state
            self.save(state)
