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
            return value
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
