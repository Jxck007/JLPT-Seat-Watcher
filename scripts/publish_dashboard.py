#!/usr/bin/env python3
"""Build public dashboard JSON from Watchtower's existing state file.

This publisher is intentionally outside the monitoring package. It never fetches a
website, parses HTML, or sends a notification. It only transforms already-recorded
state into secret-free files suitable for GitHub Pages.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 2
MAX_CHECKS = 500


def _timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _executions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("executions", [])
    if not isinstance(raw, list):
        return []
    return [
        item
        for item in raw
        if isinstance(item, dict) and _timestamp(item.get("executed_at"))
    ]


def _merge_history(
    state: dict[str, Any], existing: dict[str, Any], maximum: int
) -> list[dict[str, Any]]:
    state_history = state.get("history")
    state_payload = state_history if isinstance(state_history, dict) else {}
    merged: dict[str, dict[str, Any]] = {}

    for item in _executions(state_payload):
        merged[str(item["executed_at"])] = item
    # Existing public entries retain workflow metadata added by previous runs.
    for item in _executions(existing):
        merged[str(item["executed_at"])] = item

    ordered = sorted(
        merged.values(),
        key=lambda item: _timestamp(item["executed_at"])
        or datetime.min.replace(tzinfo=UTC),
    )
    return ordered[-maximum:]


def _records(execution: dict[str, Any]) -> list[dict[str, Any]]:
    raw = execution.get("observations", execution.get("seats", []))
    return (
        [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, list)
        else []
    )


def _daily_statistics(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for execution in executions:
        executed_at = _timestamp(execution.get("executed_at"))
        if executed_at:
            grouped[executed_at.date().isoformat()].append(execution)

    result: list[dict[str, Any]] = []
    for day, items in sorted(grouped.items()):
        targets: dict[str, dict[str, Any]] = {}
        for execution in items:
            for record in _records(execution):
                level = str(record.get("level", record.get("group", "")))
                session = str(record.get("session", record.get("label", "")))
                key = str(record.get("target", f"{level}:{session}"))
                remaining = record.get("remaining", record.get("value"))
                target = targets.setdefault(
                    key,
                    {
                        "level": level,
                        "session": session,
                        "target": key,
                        "min_remaining": remaining,
                        "max_remaining": remaining,
                        "last_remaining": remaining,
                        "last_applied": record.get("applied"),
                        "last_total": record.get("total"),
                    },
                )
                if isinstance(remaining, int | float) and not isinstance(
                    remaining, bool
                ):
                    minimum = target.get("min_remaining")
                    maximum = target.get("max_remaining")
                    target["min_remaining"] = (
                        remaining
                        if not isinstance(minimum, int | float)
                        else min(minimum, remaining)
                    )
                    target["max_remaining"] = (
                        remaining
                        if not isinstance(maximum, int | float)
                        else max(maximum, remaining)
                    )
                target["last_remaining"] = remaining
                target["last_applied"] = record.get("applied")
                target["last_total"] = record.get("total")

        count = len(items)
        result.append(
            {
                "date": day,
                "executions": count,
                "notification_count": sum(
                    int(item.get("notification_count", 0)) for item in items
                ),
                "average_execution_time_ms": round(
                    sum(float(item.get("execution_time_ms", 0.0)) for item in items)
                    / count,
                    2,
                ),
                "average_latency_ms": round(
                    sum(float(item.get("latency_ms", 0.0)) for item in items) / count, 2
                ),
                "targets": list(targets.values()),
            }
        )
    return result


def _last_alert(executions: list[dict[str, Any]]) -> dict[str, Any]:
    for execution in reversed(executions):
        notifications = execution.get("notifications")
        urgent = (
            [item for item in notifications if str(item).startswith("urgent")]
            if isinstance(notifications, list)
            else []
        )
        if urgent:
            return {
                "at": execution.get("executed_at"),
                "type": ", ".join(str(item) for item in urgent),
            }
    return {"at": None, "type": None}


def _history_csv(executions: list[dict[str, Any]]) -> str:
    fields = (
        "executed_at",
        "level",
        "session",
        "remaining",
        "applied",
        "total",
        "latency_ms",
        "execution_time_ms",
        "notification_count",
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for execution in executions:
        for record in _records(execution):
            writer.writerow(
                {
                    "executed_at": execution.get("executed_at", ""),
                    "level": record.get("level", record.get("group", "")),
                    "session": record.get("session", record.get("label", "")),
                    "remaining": record.get("remaining", record.get("value", "")),
                    "applied": record.get("applied", ""),
                    "total": record.get("total", ""),
                    "latency_ms": execution.get("latency_ms", ""),
                    "execution_time_ms": execution.get("execution_time_ms", ""),
                    "notification_count": execution.get("notification_count", ""),
                }
            )
    return output.getvalue()


def build_payloads(
    state: dict[str, Any],
    existing_history: dict[str, Any],
    *,
    now: datetime,
    workflow_status: str,
    check_interval: int,
    heartbeat_interval: int,
    timezone: ZoneInfo,
    maximum: int = MAX_CHECKS,
    run_metadata: dict[str, Any] | None = None,
    repository_metadata: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return the four public contracts without mutating monitor state."""

    current = state.get("current")
    current = current if isinstance(current, dict) else {}
    statistics = state.get("statistics")
    statistics = statistics if isinstance(statistics, dict) else {}
    notifications = state.get("notifications")
    notifications = notifications if isinstance(notifications, dict) else {}
    executions = _merge_history(state, existing_history, maximum)

    if executions and run_metadata and workflow_status.casefold() == "success":
        executions[-1] = {**executions[-1], "workflow": run_metadata}

    latest = executions[-1] if executions else {}
    last_check_value = statistics.get("last_success_at") or latest.get("executed_at")
    last_check = _timestamp(last_check_value)
    next_check = last_check + timedelta(seconds=check_interval) if last_check else None
    last_failure = statistics.get("last_failure_at")
    last_alert = _last_alert(executions)
    last_seat_alert = _timestamp(notifications.get("last_urgent_at")) or _timestamp(
        last_alert.get("at")
    )
    now_local = now.astimezone(timezone)
    today = now_local.date()
    today_executions = [
        item
        for item in executions
        if (executed := _timestamp(item.get("executed_at")))
        and executed.astimezone(timezone).date() == today
    ]
    total_checks = int(statistics.get("checks_total", 0))
    successes = int(statistics.get("successes", 0))
    uptime = round((successes / total_checks) * 100, 2) if total_checks else 0.0
    average_runtime = (
        round(
            sum(float(item.get("execution_time_ms", 0.0)) for item in executions)
            / len(executions),
            2,
        )
        if executions
        else None
    )
    average_latency = (
        round(
            sum(float(item.get("latency_ms", 0.0)) for item in executions)
            / len(executions),
            2,
        )
        if executions
        else None
    )

    heartbeat_at = _timestamp(notifications.get("last_heartbeat_at"))
    if heartbeat_at is None:
        heartbeat_status = "pending"
    elif now - heartbeat_at.astimezone(UTC) <= timedelta(
        seconds=heartbeat_interval * 2
    ):
        heartbeat_status = "healthy"
    else:
        heartbeat_status = "overdue"

    stale = last_check is None or now - last_check.astimezone(UTC) > timedelta(
        seconds=check_interval * 3
    )
    workflow_healthy = workflow_status.casefold() == "success"
    healthy = workflow_healthy and not stale and heartbeat_status != "overdue"
    failures = int(statistics.get("consecutive_failures", 0))
    if last_check is None:
        monitor_status = "waiting"
    elif failures >= 3 or workflow_status.casefold() == "failure":
        monitor_status = "failed"
    elif stale:
        monitor_status = "delayed"
    else:
        monitor_status = "healthy"
    generated_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    last_check_iso = last_check.isoformat() if last_check else None
    next_check_iso = next_check.isoformat() if next_check else None

    previous_runs = existing_history.get("workflow_runs", [])
    workflow_runs = (
        [item for item in previous_runs if isinstance(item, dict)]
        if isinstance(previous_runs, list)
        else []
    )
    if run_metadata:
        current_run = {**run_metadata, "updated_at": generated_at}
        workflow_runs = [
            item
            for item in workflow_runs
            if item.get("run_id") != current_run.get("run_id")
        ]
        workflow_runs.append(current_run)
    workflow_runs = workflow_runs[-20:]

    history = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "max_checks": maximum,
        "count": len(executions),
        "executions": executions,
        "daily_statistics": _daily_statistics(executions),
        "workflow_runs": workflow_runs,
    }
    status = {
        "schema_version": SCHEMA_VERSION,
        "level": current.get("level", current.get("group", "N4")),
        "session": current.get("session", current.get("label", "Afternoon")),
        "remaining": current.get("remaining", current.get("value")),
        "applied": current.get("applied"),
        "total": current.get("total"),
        "availability": (
            "available"
            if isinstance(current.get("remaining", current.get("value")), int | float)
            and current.get("remaining", current.get("value")) > 0
            else (
                "full"
                if isinstance(
                    current.get("remaining", current.get("value")), int | float
                )
                else "unknown"
            )
        ),
        "last_check": last_check_iso,
        "next_expected_check": next_check_iso,
        "check_interval_seconds": check_interval,
        "heartbeat_interval_seconds": heartbeat_interval,
        "workflow_status": workflow_status,
        "monitor_status": monitor_status,
        "last_heartbeat": heartbeat_at.isoformat() if heartbeat_at else None,
        "last_seat_alert": (last_seat_alert.isoformat() if last_seat_alert else None),
        "heartbeat_priority": 2,
        "seat_alert_priority": 4,
        "updated_at": generated_at,
    }
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "checks_today": len(today_executions),
        "notifications_today": sum(
            int(item.get("notification_count", 0)) for item in today_executions
        ),
        "average_runtime_ms": average_runtime,
        "average_website_latency_ms": average_latency,
        "monitor_uptime_percent": uptime,
        "last_successful_alert": last_alert,
        "repository": repository_metadata or {},
    }
    health = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "healthy": healthy,
        "last_success": last_check_iso,
        "last_failure": last_failure,
        "workflow_status": workflow_status,
        "heartbeat_status": heartbeat_status,
        "last_heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
        "stale": stale,
    }
    return {"status": status, "history": history, "metrics": metrics, "health": health}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish secret-free dashboard JSON")
    parser.add_argument("--state", type=Path, default=Path("data/state.json"))
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument(
        "--workflow-status", default=os.getenv("DASHBOARD_WORKFLOW_STATUS", "unknown")
    )
    parser.add_argument("--check-interval", type=int, default=900)
    parser.add_argument("--heartbeat-interval", type=int, default=3600)
    parser.add_argument("--timezone", default="Asia/Kolkata")
    parser.add_argument("--max-checks", type=int, default=MAX_CHECKS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    state = _load_mapping(args.state)
    existing = _load_mapping(args.docs / "history.json")
    generated_at = _timestamp(os.getenv("DASHBOARD_GENERATED_AT")) or datetime.now(UTC)
    run_url = os.getenv("DASHBOARD_RUN_URL")
    run_metadata = {
        "run_number": os.getenv("GITHUB_RUN_NUMBER"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_url": run_url,
        "status": args.workflow_status,
    }
    repository_metadata = {
        "branch": os.getenv("GITHUB_REF_NAME", "main"),
        "revision": os.getenv("GITHUB_SHA", "")[:7] or None,
        "commit_count": int(os.getenv("DASHBOARD_COMMIT_COUNT", "0")),
        "language": "Python",
    }
    payloads = build_payloads(
        state,
        existing,
        now=generated_at.astimezone(UTC),
        workflow_status=args.workflow_status,
        check_interval=args.check_interval,
        heartbeat_interval=args.heartbeat_interval,
        timezone=ZoneInfo(args.timezone),
        maximum=max(1, args.max_checks),
        run_metadata=run_metadata if run_url else None,
        repository_metadata=repository_metadata,
    )
    for name, payload in payloads.items():
        _atomic_json(args.docs / f"{name}.json", payload)
    _atomic_text(
        args.docs / "history.csv",
        _history_csv(payloads["history"]["executions"]),
    )
    print(
        f"Published {len(payloads)} dashboard files with "
        f"{payloads['history']['count']} retained checks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
