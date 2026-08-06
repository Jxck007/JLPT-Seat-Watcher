from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _execution(checked_at: datetime, remaining: int = 2) -> dict[str, object]:
    observation = {
        "level": "N4",
        "session": "Afternoon",
        "remaining": remaining,
        "applied": 850 - remaining,
        "total": 850,
    }
    return {
        "executed_at": checked_at.isoformat(),
        "execution_time_ms": 250.0,
        "latency_ms": 125.0,
        "notification_count": 1,
        "notifications": ["heartbeat"],
        "observations": [observation],
        "seats": [observation],
    }


def _run_publisher(
    tmp_path: Path, state: dict[str, object], now: datetime, maximum: int = 500
) -> tuple[subprocess.CompletedProcess[str], Path]:
    state_path = tmp_path / "state.json"
    docs = tmp_path / "docs"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    environment = {
        **os.environ,
        "DASHBOARD_GENERATED_AT": now.isoformat(),
        "DASHBOARD_WORKFLOW_STATUS": "success",
        "DASHBOARD_COMMIT_COUNT": "42",
        "GITHUB_SHA": "1234567890abcdef",
        "GITHUB_REF_NAME": "main",
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/publish_dashboard.py",
            "--state",
            str(state_path),
            "--docs",
            str(docs),
            "--max-checks",
            str(maximum),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result, docs


def test_public_contracts_are_live_bounded_and_secret_free(tmp_path: Path) -> None:
    now = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
    checks = [_execution(now - timedelta(minutes=index)) for index in range(6)]
    state = {
        "current": checks[0]["observations"][0],
        "history": {"executions": checks},
        "notifications": {"last_heartbeat_at": now.isoformat()},
        "statistics": {
            "checks_total": 10,
            "successes": 9,
            "consecutive_failures": 0,
            "last_success_at": now.isoformat(),
            "last_failure_at": (now - timedelta(days=1)).isoformat(),
        },
        "ntfy_token": "must-not-be-published",
    }

    result, docs = _run_publisher(tmp_path, state, now, maximum=3)
    assert result.returncode == 0, result.stderr
    payloads = {
        name: json.loads((docs / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("status", "history", "metrics", "health")
    }
    assert set(payloads) == {"status", "history", "metrics", "health"}
    assert payloads["history"]["count"] == 3
    assert len(payloads["history"]["executions"]) == 3
    assert payloads["status"]["current_remaining"] == 2
    assert payloads["status"]["next_check"] == (now + timedelta(minutes=5)).isoformat()
    assert payloads["metrics"]["checks_today"] == 3
    assert payloads["metrics"]["notifications_today"] == 3
    assert payloads["metrics"]["monitor_uptime_percent"] == 90.0
    assert payloads["health"]["healthy"] is True
    assert "must-not-be-published" not in json.dumps(payloads)


def test_publisher_writes_all_dashboard_files(tmp_path: Path) -> None:
    now = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
    state = {
        "current": _execution(now)["observations"][0],
        "history": {"executions": [_execution(now)]},
        "notifications": {"last_heartbeat_at": now.isoformat()},
        "statistics": {
            "checks_total": 1,
            "successes": 1,
            "consecutive_failures": 0,
            "last_success_at": now.isoformat(),
            "last_failure_at": None,
        },
    }
    result, docs = _run_publisher(tmp_path, state, now)

    assert result.returncode == 0, result.stderr
    assert {path.name for path in docs.iterdir()} == {
        "status.json",
        "history.json",
        "history.csv",
        "metrics.json",
        "health.json",
    }
    metrics = json.loads((docs / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["repository"]["commit_count"] == 42
    assert metrics["repository"]["revision"] == "1234567"
