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

from watchtower.adapters import WebsiteAdapter
from watchtower.adapters.jlpt_chennai.parser import parse_levels
from watchtower.adapters.jlpt_chennai.scraper import Scraper
from watchtower.config import ConfigurationError, Settings
from watchtower.history import write_dashboard_files, write_history_files
from watchtower.logging_setup import configure_logging
from watchtower.models import MonitorObservation
from watchtower.monitor import MonitorService
from watchtower.notifier import Notifier, Priority
from watchtower.state import StateError, StateStore

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
        return "Website monitor has not completed a successful check."
    successes = int(stats["successes"])
    average_duration = stats["duration_total_ms"] / max(successes, 1)
    average_latency = stats["latency_total_ms"] / max(successes, 1)
    targets = (
        state.get("targets")
        or state.get("levels")
        or {
            str(current.get("target", current.get("level", "default"))): {
                "current": current
            }
        }
    )
    lines = ["Watchtower Website Monitor", "=========================="]
    for target_state in targets.values():
        observation = target_state.get("current")
        if not observation:
            continue
        if "level" in observation:
            lines.extend(
                (
                    f"\n{observation['level']} ({observation['session']})",
                    f"Total:            {observation['total']}",
                    f"Applied:          {observation['applied']}",
                    f"Remaining:        {observation['remaining']}",
                )
            )
        else:
            label = observation.get("label", observation.get("target", "Target"))
            lines.extend(
                (
                    f"\n{label}",
                    f"Value:            {observation.get('value')}",
                    f"Available:        {observation.get('available')}",
                )
            )
    lines.extend(
        (
            f"\nLast success:     {stats['last_success_at']}",
            f"Fetch method:     {current['fetch_method']}",
            f"Website latency:  {current['latency_ms']:.0f} ms",
            f"Average latency:  {average_latency:.0f} ms",
            f"Average duration: {average_duration:.0f} ms",
            f"Successful checks:{successes:>6}",
            f"Failed checks:    {stats['failures']:>6}",
        )
    )
    return "\n".join(lines)


def _github_summary(title: str, lines: list[str]) -> None:
    destination = os.getenv("GITHUB_STEP_SUMMARY")
    if not destination:
        return
    with Path(destination).open("a", encoding="utf-8") as handle:
        handle.write(f"## {title}\n\n")
        handle.write("\n".join(lines) + "\n")


def _observation_summary(observation: MonitorObservation) -> str:
    value = observation.to_dict()
    if "level" in value:
        return (
            f"- {value['level']} ({value['session']}): "
            f"**{value['remaining']} remaining**, "
            f"{value['applied']} / {value['total']} applied"
        )
    return f"- {observation.target_label}: **{observation.current_value}**"


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
    parser = argparse.ArgumentParser(description="Run the Watchtower website monitor")
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
    history_export = subcommands.add_parser(
        "export-history", help="Generate retained JSON and CSV history files"
    )
    history_export.add_argument("--output-dir", type=Path)
    dashboard_export = subcommands.add_parser(
        "export-dashboard", help="Generate secret-free GitHub Pages data files"
    )
    dashboard_export.add_argument("--output-dir", type=Path, default=Path("docs"))
    subcommands.add_parser("cleanup", help="Delete expired runtime artifacts")
    return parser


def _run_check(settings: Settings) -> int:
    result = MonitorService(settings).run_once()
    _cleanup(settings)
    observations = result.all_observations
    print(
        json.dumps(
            {
                **result.observation.to_dict(),
                "observations": [item.to_dict() for item in observations],
                "changed": result.changed,
                "notifications": result.notifications,
                "duration_ms": result.duration_ms,
            },
            indent=2,
        )
    )
    _github_summary(
        (
            "JLPT N4 monitor"
            if settings.adapter == "jlpt_chennai" and settings.watched_levels == ("N4",)
            else (
                "JLPT seat monitor"
                if settings.adapter == "jlpt_chennai"
                else "Watchtower monitor"
            )
        ),
        [
            *[_observation_summary(item) for item in observations],
            f"- Fetch method: `{observations[0].fetch_method}`",
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
        if settings.adapter == "jlpt_chennai":
            scraper = Scraper(settings)
            fetch_all = getattr(scraper, "fetch_all", None)
            observations = (
                tuple(fetch_all()) if callable(fetch_all) else (scraper.fetch(),)
            )
        else:
            adapter = WebsiteAdapter.create(settings)
            observations = adapter.validate(adapter.parse(adapter.fetch()))
        scraper_payload: object = (
            observations[0].to_dict()
            if len(observations) == 1
            else [item.to_dict() for item in observations]
        )
        print(json.dumps(scraper_payload, indent=2))
        _github_summary(
            "Watchtower live adapter test",
            [
                "- Result: **passed**",
                *[
                    (
                        f"- {item.level} remaining: **{item.remaining}**"
                        if hasattr(item, "level")
                        else f"- {item.target_label}: **{item.current_value}**"
                    )
                    for item in observations
                ],
                f"- Method: `{observations[0].fetch_method}`",
            ],
        )
        return 0
    if command == "parser-test":
        html = args.html.read_text(encoding="utf-8") if args.html else PARSER_SAMPLE
        parsed = parse_levels(html, settings.watched_levels, settings.session_mode)
        payload: object = (
            asdict(parsed[0]) if len(parsed) == 1 else [asdict(item) for item in parsed]
        )
        print(json.dumps(payload, indent=2))
        return 0
    if command == "notify-test":
        priorities = {
            "silent": Priority.SILENT,
            "normal": Priority.NORMAL,
            "high": Priority.HIGH,
            "emergency": Priority.EMERGENCY,
        }
        now = datetime.now(settings.timezone).isoformat()
        test_title = (
            "JLPT Seat Watcher Test"
            if settings.adapter == "jlpt_chennai"
            else "Watchtower Notification Test"
        )
        Notifier.create(settings).send(
            test_title,
            f"This is a manual test notification.\n"
            f"Watched levels: {', '.join(settings.watched_levels)}\n"
            f"Timestamp: {now}",
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
    if command == "export-history":
        destination = args.output_dir or settings.data_dir
        write_history_files(store.load(recover=False), destination)
        print(f"History JSON and CSV exported to {destination}")
        return 0
    if command == "export-dashboard":
        write_dashboard_files(store.load(recover=False), args.output_dir)
        print(f"Dashboard data exported to {args.output_dir}")
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
