from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from jlpt_seat_watcher import cli
from jlpt_seat_watcher.config import ConfigurationError, Settings
from jlpt_seat_watcher.models import CheckResult, SeatObservation
from jlpt_seat_watcher.state import StateStore


def _observation(settings: Settings, now: datetime | None = None) -> SeatObservation:
    return SeatObservation(
        session="Afternoon",
        level="N4",
        total=850,
        applied=850,
        remaining=0,
        checked_at=now or datetime.now(settings.timezone),
        latency_ms=123.4,
        fetch_method="requests",
    )


def _args(command: str, **kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(command=command, **kwargs)


def _write_success_state(settings: Settings, checked_at: datetime) -> None:
    store = StateStore(settings.state_path)
    state = store.load()
    state["current"] = _observation(settings, checked_at).to_dict()
    state["statistics"].update(
        {
            "checks_total": 2,
            "successes": 2,
            "failures": 1,
            "duration_total_ms": 400.0,
            "latency_total_ms": 200.0,
            "last_success_at": checked_at.isoformat(),
        }
    )
    store.save(state)


def test_status_stats_export_and_health(
    settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli._execute(_args("status"), settings) == 1
    assert "not completed" in capsys.readouterr().out
    checked_at = datetime.now(settings.timezone)
    _write_success_state(settings, checked_at)

    assert cli._execute(_args("status"), settings) == 0
    assert "Remaining:        0" in capsys.readouterr().out
    assert cli._execute(_args("stats"), settings) == 0
    assert json.loads(capsys.readouterr().out)["successes"] == 2
    assert cli._execute(_args("health"), settings) == 0
    assert "HEALTHY" in capsys.readouterr().out

    destination = tmp_path / "export.json"
    assert cli._execute(_args("export-state", output=destination), settings) == 0
    assert json.loads(destination.read_text(encoding="utf-8"))["schema_version"] == 1
    assert cli._execute(_args("export-state", output=None), settings) == 0
    assert '"schema_version": 1' in capsys.readouterr().out

    history_dir = tmp_path / "history-export"
    assert cli._execute(_args("export-history", output_dir=history_dir), settings) == 0
    assert (history_dir / "history.json").exists()
    assert (history_dir / "history.csv").exists()
    dashboard_dir = tmp_path / "dashboard-export"
    assert (
        cli._execute(_args("export-dashboard", output_dir=dashboard_dir), settings) == 0
    )
    assert (dashboard_dir / "status.json").exists()


def test_health_detects_missing_and_stale(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli._execute(_args("health"), settings) == 1
    assert "no successful" in capsys.readouterr().out
    stale = datetime.now(settings.timezone) - timedelta(hours=2)
    _write_success_state(settings, stale)
    assert cli._execute(_args("health"), settings) == 1
    assert "stale" in capsys.readouterr().out


def test_status_lists_both_sessions_for_same_level(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime.now(settings.timezone)
    forenoon = SeatObservation("Forenoon", "N4", 100, 99, 1, now, 100.0, "requests")
    afternoon = SeatObservation("Afternoon", "N4", 200, 198, 2, now, 100.0, "requests")
    store = StateStore(settings.state_path)
    state = store.load()
    state["current"] = forenoon.to_dict()
    state["targets"] = {
        "N4:Forenoon": {"current": forenoon.to_dict()},
        "N4:Afternoon": {"current": afternoon.to_dict()},
    }
    state["statistics"].update(
        {
            "successes": 1,
            "last_success_at": now.isoformat(),
            "duration_total_ms": 100.0,
            "latency_total_ms": 100.0,
        }
    )
    store.save(state)

    assert cli._execute(_args("status"), settings) == 0
    output = capsys.readouterr().out
    assert "N4 (Forenoon)" in output
    assert "N4 (Afternoon)" in output
    assert "Remaining:        1" in output
    assert "Remaining:        2" in output


def test_parser_test_and_cleanup(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli._execute(_args("parser-test", html=None), settings) == 0
    assert json.loads(capsys.readouterr().out)["level"] == "N4"

    old = settings.logs_dir / "snapshots" / "old.html"
    old.parent.mkdir(parents=True)
    old.write_text("diagnostic", encoding="utf-8")
    expired = time.time() - (settings.log_retention_days + 1) * 86400
    os.utime(old, (expired, expired))
    assert cli._execute(_args("cleanup"), settings) == 0
    assert not old.exists()


def test_scraper_check_and_notification_commands(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observation = _observation(settings)

    class FakeScraper:
        def __init__(self, _settings: Settings) -> None:
            pass

        def fetch(self) -> SeatObservation:
            return observation

    class FakeService:
        def __init__(self, _settings: Settings) -> None:
            pass

        def run_once(self) -> CheckResult:
            return CheckResult(observation, False, ("heartbeat",), 150.0)

    delivered: list[tuple[str, int]] = []

    class FakeNotifier:
        def send(self, title: str, message: str, priority: int, **kwargs: Any) -> None:
            del message, kwargs
            delivered.append((title, int(priority)))

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(cli, "Scraper", FakeScraper)
    monkeypatch.setattr(cli, "MonitorService", FakeService)
    monkeypatch.setattr(cli.Notifier, "create", lambda _settings: FakeNotifier())

    assert cli._execute(_args("scraper-test"), settings) == 0
    assert "passed" in summary.read_text(encoding="utf-8")
    assert cli._execute(_args("check"), settings) == 0
    assert "JLPT N4 monitor" in summary.read_text(encoding="utf-8")
    assert cli._execute(_args("notify-test", priority="emergency"), settings) == 0
    assert delivered == [("JLPT Seat Watcher Test", 5)]
    capsys.readouterr()


def test_daemon_runs_a_cycle_then_stops(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class FakeService:
        def __init__(self, _settings: Settings) -> None:
            pass

        def run_once(self) -> None:
            calls.append("check")

    class FakeEvent:
        stopped = False

        def is_set(self) -> bool:
            return self.stopped

        def set(self) -> None:
            self.stopped = True

        def wait(self, timeout: float) -> None:
            del timeout
            self.stopped = True

    monkeypatch.setattr(cli, "MonitorService", FakeService)
    monkeypatch.setattr(cli, "Event", FakeEvent)
    monkeypatch.setattr(cli.signal, "signal", lambda *_: None)
    monkeypatch.setattr(cli, "_cleanup", lambda _: 0)
    assert cli._run_daemon(settings) == 0
    assert calls == ["check"]


def test_main_handles_configuration_and_unexpected_errors(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    assert cli.main(["parser-test"]) == 0
    assert '"level": "N4"' in capsys.readouterr().out

    def bad_config() -> Settings:
        raise ConfigurationError("broken environment")

    monkeypatch.setattr(cli.Settings, "from_env", bad_config)
    assert cli.main(["status"]) == 2
    assert "broken environment" in capsys.readouterr().err

    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(
        cli, "_execute", lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert cli.main(["status"]) == 1
    assert "boom" in capsys.readouterr().err
