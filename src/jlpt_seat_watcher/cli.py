"""Command-line interfaces for operators and automation."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

from jlpt_seat_watcher.config import ConfigurationError, Settings
from jlpt_seat_watcher.logging_setup import configure_logging
from jlpt_seat_watcher.monitor import MonitorService
from jlpt_seat_watcher.notifier import NtfyNotifier, Priority
from jlpt_seat_watcher.parser import parse_n4
from jlpt_seat_watcher.scraper import Scraper
from jlpt_seat_watcher.state import StateError, StateStore

LOGGER = logging.getLogger(__name__)

PARSER_SAMPLE = """
<div class="table-container1">
  <div class="cell1 section-header1">FORENOON EXAM APPLICATIONS</div>
  <div class="cell1">N1 Total: <span>200</span></div>
  <div class="cell1">Applied: <span>20</span></div>
  <div class="cell1">Remaining: <span>180</span></div>
  <div class="cell1 section-header1">AFTERNOON EXAM APPLICATIONS</div>
  <div class="cell1">N4 Total: <span>850</span></div>
  <div class="cell1">Applied: <span>850</span></div>
  <div class="cell1">Remaining: <span>0</span></div>
</div>
"""


def _state_summary(state: dict[str, Any]) -> str:
    current = state.get("current")
    stats = state["statistics"]
    if current is None:
        return "JLPT N4 monitor has not completed a successful check."
    successes = int(stats["successes"])
    average_duration = stats["duration_total_ms"] / max(successes, 1)
    average_latency = stats["latency_total_ms"] / max(successes, 1)
    return "\n".join(
        (
            "JLPT N4 Seat Watcher",
            "====================",
            f"Session:          {current['session']}",
            f"Total:            {current['total']}",
            f"Applied:          {current['applied']}",
            f"Remaining:        {current['remaining']}",
            f"Last success:     {stats['last_success_at']}",
            f"Fetch method:     {current['fetch_method']}",
            f"Website latency:  {current['latency_ms']:.0f} ms",
            f"Average latency:  {average_latency:.0f} ms",
            f"Average duration: {average_duration:.0f} ms",
            f"Successful checks:{successes:>6}",
            f"Failed checks:    {stats['failures']:>6}",
        )
    )


def _github_summary(title: str, lines: list[str]) -> None:
    destination = os.getenv("GITHUB_STEP_SUMMARY")
    if not destination:
        return
    with Path(destination).open("a", encoding="utf-8") as handle:
        handle.write(f"## {title}\n\n")
        handle.write("\n".join(lines) + "\n")


def _cleanup(settings: Settings) -> int:
    cutoff = time.time() - (settings.log_retention_days * 86400)
    removed = 0
    candidates = [settings.logs_dir, settings.logs_dir / "snapshots"]
    for directory in candidates:
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if (
                path.is_file()
                and path.suffix in {".jsonl", ".log", ".html", ".png"}
                and path.stat().st_mtime < cutoff
            ):
                path.unlink()
                removed += 1
    return removed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor JLPT Chennai N4 seats")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("check", help="Run one monitored check")
    subcommands.add_parser("daemon", help="Run continuously")
    subcommands.add_parser("status", help="Show current state")
    subcommands.add_parser("stats", help="Show machine-readable statistics")
    subcommands.add_parser("health", help="Check monitor freshness")
    subcommands.add_parser(
        "scraper-test", help="Scrape and validate without state changes"
    )
    parser_test = subcommands.add_parser(
        "parser-test", help="Parse a file or built-in fixture"
    )
    parser_test.add_argument("html", nargs="?", type=Path)
    notify = subcommands.add_parser(
        "notify-test", help="Send a labelled test notification"
    )
    notify.add_argument(
        "--priority",
        choices=("silent", "normal", "high", "emergency"),
        default="high",
    )
    export = subcommands.add_parser("export-state", help="Export state as JSON")
    export.add_argument("--output", type=Path)
    subcommands.add_parser("cleanup", help="Delete expired runtime artifacts")
    return parser


def _run_check(settings: Settings) -> int:
    result = MonitorService(settings).run_once()
    _cleanup(settings)
    observation = result.observation
    print(
        json.dumps(
            {
                **observation.to_dict(),
                "changed": result.changed,
                "notifications": result.notifications,
                "duration_ms": result.duration_ms,
            },
            indent=2,
        )
    )
    _github_summary(
        "JLPT N4 monitor",
        [
            f"- Remaining: **{observation.remaining}**",
            f"- Applied / total: {observation.applied} / {observation.total}",
            f"- Fetch method: `{observation.fetch_method}`",
            f"- Duration: {result.duration_ms:.0f} ms",
            f"- Notifications: {', '.join(result.notifications) or 'none'}",
        ],
    )
    return 0


def _run_daemon(settings: Settings) -> int:
    stopped = Event()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOGGER.info(
        "Continuous monitor started", extra={"interval": settings.check_interval}
    )
    while not stopped.is_set():
        cycle_started = time.monotonic()
        try:
            MonitorService(settings).run_once()
            _cleanup(settings)
        except Exception:
            LOGGER.exception("Monitor cycle failed; daemon will continue")
        elapsed = time.monotonic() - cycle_started
        stopped.wait(max(0.0, settings.check_interval - elapsed))
    LOGGER.info("Continuous monitor stopped")
    return 0


def _execute(args: argparse.Namespace, settings: Settings) -> int:
    store = StateStore(settings.state_path)
    command = args.command or "check"
    if command == "check":
        return _run_check(settings)
    if command == "daemon":
        return _run_daemon(settings)
    if command == "status":
        state = store.load(recover=False)
        print(_state_summary(state))
        return 0 if state.get("current") else 1
    if command == "stats":
        print(json.dumps(store.load(recover=False)["statistics"], indent=2))
        return 0
    if command == "health":
        state = store.load(recover=False)
        last_success = state["statistics"].get("last_success_at")
        if not last_success:
            print("UNHEALTHY: no successful check has been recorded")
            return 1
        checked = datetime.fromisoformat(str(last_success))
        stale_after = timedelta(seconds=max(900, settings.check_interval * 3))
        if datetime.now(settings.timezone) - checked > stale_after:
            print(f"UNHEALTHY: last success is stale ({last_success})")
            return 1
        print(f"HEALTHY: last successful check {last_success}")
        return 0
    if command == "scraper-test":
        observation = Scraper(settings).fetch()
        print(json.dumps(observation.to_dict(), indent=2))
        _github_summary(
            "JLPT live scraper test",
            [
                "- Result: **passed**",
                f"- N4 remaining: **{observation.remaining}**",
                f"- Method: `{observation.fetch_method}`",
            ],
        )
        return 0
    if command == "parser-test":
        html = args.html.read_text(encoding="utf-8") if args.html else PARSER_SAMPLE
        parsed = parse_n4(html)
        print(json.dumps(asdict(parsed), indent=2))
        return 0
    if command == "notify-test":
        priorities = {
            "silent": Priority.SILENT,
            "normal": Priority.NORMAL,
            "high": Priority.HIGH,
            "emergency": Priority.EMERGENCY,
        }
        now = datetime.now(settings.timezone).isoformat()
        NtfyNotifier(settings).send(
            "JLPT Seat Watcher Test",
            f"This is a manual test notification.\nSent: {now}",
            priorities[args.priority],
            tags=("test_tube", "jlpt"),
        )
        print("Test notification delivered.")
        return 0
    if command == "export-state":
        serialized = json.dumps(store.load(recover=False), indent=2) + "\n"
        if args.output:
            args.output.write_text(serialized, encoding="utf-8")
            print(f"State exported to {args.output}")
        else:
            print(serialized, end="")
        return 0
    if command == "cleanup":
        print(f"Removed {_cleanup(settings)} expired runtime artifacts.")
        return 0
    raise AssertionError(f"Unhandled command: {command}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        configure_logging(settings.logs_dir, settings.log_level)
        return _execute(args, settings)
    except (ConfigurationError, StateError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        LOGGER.exception("Command failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
