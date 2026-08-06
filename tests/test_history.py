from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from jlpt_seat_watcher.history import (
    dashboard_status,
    record_execution,
    write_dashboard_files,
    write_history_files,
)
from jlpt_seat_watcher.models import SeatObservation
from jlpt_seat_watcher.state import new_state


def _observation(
    now: datetime, level: str = "N4", session: str = "Afternoon", remaining: int = 2
) -> SeatObservation:
    return SeatObservation(
        session=session,
        level=level,
        total=850,
        applied=850 - remaining,
        remaining=remaining,
        checked_at=now,
        latency_ms=125.5,
        fetch_method="requests",
    )


def test_records_daily_statistics_and_prunes_old_executions() -> None:
    state = new_state()
    now = datetime.fromisoformat("2026-08-06T10:00:00+05:30")
    old = _observation(now - timedelta(days=31), remaining=5)
    record_execution(state, (old,), 300.0, (), 30)

    first = _observation(now, remaining=3)
    second = _observation(now + timedelta(minutes=5), remaining=1)
    record_execution(state, (first,), 200.0, ("heartbeat",), 30)
    history = record_execution(state, (second,), 400.0, ("urgent", "summary"), 30)

    assert len(history["executions"]) == 2
    assert history["executions"][-1]["notification_count"] == 2
    daily = history["daily_statistics"][0]
    assert daily["executions"] == 2
    assert daily["notification_count"] == 3
    assert daily["average_execution_time_ms"] == 300.0
    assert daily["average_latency_ms"] == 125.5
    assert daily["targets"][0]["min_remaining"] == 1
    assert daily["targets"][0]["max_remaining"] == 3


def test_writes_json_csv_and_secret_free_dashboard(tmp_path: Path) -> None:
    state = new_state()
    now = datetime.fromisoformat("2026-08-06T10:00:00+05:30")
    observations = (
        _observation(now, "N4", "Afternoon", 2),
        _observation(now, "N2", "Forenoon", 4),
    )
    record_execution(state, observations, 321.25, ("urgent:N4",), 30)
    state["current"] = observations[0].to_dict()
    state["statistics"]["last_success_at"] = now.isoformat()

    write_history_files(state, tmp_path / "data")
    payload = json.loads((tmp_path / "data/history.json").read_text())
    assert payload["retention_days"] == 30
    with (tmp_path / "data/history.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["level"], row["remaining"]) for row in rows] == [
        ("N4", "2"),
        ("N2", "4"),
    ]
    assert rows[0]["execution_time_ms"] == "321.25"
    assert rows[0]["notification_count"] == "1"

    write_dashboard_files(state, tmp_path / "docs")
    status = json.loads((tmp_path / "docs/status.json").read_text())
    assert status["seats"]["remaining"] == 2
    assert status["checks"]["duration_ms"] == 321.25
    assert status["last_notification"]["type"] == "urgent:N4"
    serialized = " ".join(path.read_text() for path in (tmp_path / "docs").iterdir())
    assert "token" not in serialized.casefold()


def test_dashboard_status_handles_empty_and_failed_state() -> None:
    state = new_state()
    assert dashboard_status(state)["project_status"] == "yellow"
    state["current"] = {
        "level": "N4",
        "session": "Afternoon",
        "remaining": 0,
        "applied": 850,
        "total": 850,
    }
    state["statistics"]["consecutive_failures"] = 3
    assert dashboard_status(state)["project_status"] == "red"
