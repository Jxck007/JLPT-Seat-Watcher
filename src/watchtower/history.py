"""Bounded execution history and secret-free dashboard exports."""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from watchtower.models import MonitorObservation

HISTORY_SCHEMA_VERSION = 1
CSV_FIELDS = (
    "executed_at",
    "level",
    "session",
    "remaining",
    "applied",
    "total",
    "latency_ms",
    "execution_time_ms",
    "notification_count",
    "target",
    "value",
    "available",
    "data_json",
)


def _parse_timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _retained_executions(
    executions: object, now: datetime, retention_days: int
) -> list[dict[str, Any]]:
    if not isinstance(executions, list):
        return []
    cutoff = now - timedelta(days=retention_days)
    retained: list[dict[str, Any]] = []
    for item in executions:
        if not isinstance(item, dict):
            continue
        timestamp = _parse_timestamp(item.get("executed_at"))
        if timestamp is None:
            continue
        if timestamp.tzinfo is None and cutoff.tzinfo is not None:
            timestamp = timestamp.replace(tzinfo=cutoff.tzinfo)
        if timestamp >= cutoff:
            retained.append(item)
    return retained


def _daily_statistics(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for execution in executions:
        timestamp = _parse_timestamp(execution.get("executed_at"))
        if timestamp is not None:
            grouped[timestamp.date().isoformat()].append(execution)

    daily: list[dict[str, Any]] = []
    for day, items in sorted(grouped.items()):
        target_values: dict[str, dict[str, Any]] = {}
        for item in items:
            records = item.get("observations", item.get("seats", []))
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                level = str(record.get("level", record.get("group", "")))
                session = str(record.get("session", record.get("label", "")))
                key = str(record.get("target", f"{level}:{session}"))
                raw_value = record.get("remaining", record.get("value"))
                target = target_values.setdefault(
                    key,
                    {
                        "level": level,
                        "session": session,
                        "target": key,
                        "min_remaining": raw_value,
                        "max_remaining": raw_value,
                        "last_remaining": raw_value,
                        "last_applied": record.get("applied"),
                        "last_total": record.get("total"),
                    },
                )
                if isinstance(raw_value, int | float) and not isinstance(
                    raw_value, bool
                ):
                    target["min_remaining"] = min(
                        float(target["min_remaining"]), raw_value
                    )
                    target["max_remaining"] = max(
                        float(target["max_remaining"]), raw_value
                    )
                target["last_remaining"] = raw_value
                target["last_applied"] = record.get("applied")
                target["last_total"] = record.get("total")

        count = len(items)
        daily.append(
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
                    sum(float(item.get("latency_ms", 0.0)) for item in items) / count,
                    2,
                ),
                "targets": list(target_values.values()),
            }
        )
    return daily


def record_execution(
    state: dict[str, Any],
    observations: Iterable[MonitorObservation],
    execution_time_ms: float,
    notifications: Iterable[str],
    retention_days: int,
) -> dict[str, Any]:
    """Append a successful execution and prune entries outside the window."""

    observed = tuple(observations)
    if not observed:
        raise ValueError("History requires at least one observation")
    now = observed[0].checked_at
    history = state.get("history")
    if not isinstance(history, dict):
        history = {}
        state["history"] = history
    executions = _retained_executions(history.get("executions"), now, retention_days)
    sent = tuple(notifications)
    records = [item.to_history_dict() for item in observed]
    execution = {
        "executed_at": now.isoformat(),
        "execution_time_ms": round(execution_time_ms, 2),
        "latency_ms": round(max(item.latency_ms for item in observed), 2),
        "notification_count": len(sent),
        "notifications": list(sent),
        "observations": records,
    }
    if all("level" in record and "session" in record for record in records):
        execution["seats"] = records
    executions.append(execution)
    history.update(
        {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "retention_days": retention_days,
            "executions": executions,
            "daily_statistics": _daily_statistics(executions),
        }
    )
    return history


def history_payload(state: dict[str, Any]) -> dict[str, Any]:
    history = state.get("history")
    if not isinstance(history, dict):
        history = {}
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "retention_days": int(history.get("retention_days", 30)),
        "executions": history.get("executions", []),
        "daily_statistics": history.get("daily_statistics", []),
    }


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


def _csv_content(executions: object) -> str:
    from io import StringIO

    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    if not isinstance(executions, list):
        return output.getvalue()
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        records = execution.get("observations", execution.get("seats", []))
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            writer.writerow(
                {
                    "executed_at": execution.get("executed_at", ""),
                    "level": record.get("level", ""),
                    "session": record.get("session", ""),
                    "remaining": record.get("remaining", ""),
                    "applied": record.get("applied", ""),
                    "total": record.get("total", ""),
                    "latency_ms": execution.get("latency_ms", ""),
                    "execution_time_ms": execution.get("execution_time_ms", ""),
                    "notification_count": execution.get("notification_count", ""),
                    "target": record.get("target", ""),
                    "value": record.get("value", ""),
                    "available": record.get("available", ""),
                    "data_json": json.dumps(
                        record.get("values", {}), ensure_ascii=False, sort_keys=True
                    ),
                }
            )
    return output.getvalue()


def write_history_files(state: dict[str, Any], directory: Path) -> None:
    """Write the retained history as JSON and a flattened CSV file."""

    payload = history_payload(state)
    _atomic_text(
        directory / "history.json",
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _atomic_text(directory / "history.csv", _csv_content(payload["executions"]))


def _last_notification(executions: object) -> dict[str, Any]:
    if isinstance(executions, list):
        for execution in reversed(executions):
            if not isinstance(execution, dict):
                continue
            notifications = execution.get("notifications")
            if isinstance(notifications, list) and notifications:
                return {
                    "at": execution.get("executed_at"),
                    "type": ", ".join(str(item) for item in notifications),
                }
    return {"at": None, "type": None}


def dashboard_status(state: dict[str, Any]) -> dict[str, Any]:
    """Create the public status contract without runtime credentials."""

    current = state.get("current")
    if not isinstance(current, dict):
        current = {}
    statistics = state.get("statistics")
    if not isinstance(statistics, dict):
        statistics = {}
    history = history_payload(state)
    executions = history["executions"]
    latest = executions[-1] if isinstance(executions, list) and executions else {}
    failures = int(statistics.get("consecutive_failures", 0))
    project_status = "red" if failures >= 3 else "yellow" if failures else "green"
    return {
        "schema_version": 1,
        "project_status": project_status if current else "yellow",
        "updated_at": statistics.get("last_success_at"),
        "current_exam": current.get("level", "N4"),
        "current_session": (
            f"{current.get('session')} session"
            if current.get("session")
            else "Afternoon session"
        ),
        "seats": {
            "remaining": current.get("remaining"),
            "applied": current.get("applied"),
            "total": current.get("total"),
        },
        "checks": {
            "last_success_at": statistics.get("last_success_at"),
            "duration_ms": latest.get("execution_time_ms"),
        },
        "last_notification": _last_notification(executions),
    }


def write_dashboard_files(state: dict[str, Any], directory: Path) -> None:
    """Publish only the safe status and retained history dashboard contracts."""

    write_history_files(state, directory)
    _atomic_text(
        directory / "status.json",
        json.dumps(dashboard_status(state), ensure_ascii=False, indent=2) + "\n",
    )
