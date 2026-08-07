"""Domain-neutral state comparison, scheduling, and notification engine."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, cast

from watchtower.adapters import NotificationEvent, WebsiteAdapter
from watchtower.config import Settings
from watchtower.history import record_execution, write_history_files
from watchtower.models import MonitorObservation, MonitorResult, Scalar
from watchtower.notifier import NotificationError, Notifier, Priority
from watchtower.state import StateStore

LOGGER = logging.getLogger(__name__)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _is_due(last: object, now: datetime, seconds: int) -> bool:
    parsed = _parse_time(last)
    return parsed is None or now - parsed >= timedelta(seconds=seconds)


class MonitorEngine:
    """Generic monitor engine whose website behavior is supplied by an adapter."""

    def __init__(
        self,
        settings: Settings,
        *,
        adapter: WebsiteAdapter[Any] | None = None,
        notifier: Notifier | None = None,
        store: StateStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        selected = adapter or WebsiteAdapter.create(settings)
        self.adapter = cast(WebsiteAdapter[MonitorObservation], selected)
        self.notifier = notifier or Notifier.create(settings)
        self.store = store or StateStore(settings.state_path)
        self.clock = clock or (lambda: datetime.now(settings.timezone))

    def _send(
        self,
        sent: list[str],
        kind: str,
        observations: tuple[MonitorObservation, ...],
        priority: Priority,
        *,
        observation: MonitorObservation | None = None,
        daily_statistics: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> bool:
        if not self.notifier.configured:
            hint = getattr(self.notifier, "configuration_hint", "selected provider")
            LOGGER.warning("Notification skipped because %s is not configured", hint)
            if state is not None and now is not None:
                self._record_notification_failure(state, kind, now)
            return False
        event = NotificationEvent(
            kind=kind,
            observations=observations,
            observation=observation,
            priority=priority,
            daily_statistics=daily_statistics,
        )
        try:
            self.adapter.notify(event, self.notifier)
            sent.append(kind)
            return True
        except NotificationError:
            LOGGER.exception("Notification failed", extra={"notification_type": kind})
            if state is not None and now is not None:
                self._record_notification_failure(state, kind, now)
            return False

    @staticmethod
    def _record_notification_failure(
        state: dict[str, Any], kind: str, now: datetime
    ) -> None:
        notifications = state.setdefault("notifications", {})
        failures = notifications.setdefault(
            "failures", {"count": 0, "last_at": None, "last_kind": None}
        )
        failures["count"] = int(failures.get("count", 0)) + 1
        failures["last_at"] = now.isoformat()
        failures["last_kind"] = kind

    def _record_failure(self, now: datetime) -> None:
        with self.store.transaction() as state:
            stats = state["statistics"]
            stats["checks_total"] += 1
            stats["failures"] += 1
            stats["consecutive_failures"] += 1
            stats["last_failure_at"] = now.isoformat()

    def _fetch_observations(self) -> tuple[MonitorObservation, ...]:
        payload = self.adapter.fetch()
        parsed = self.adapter.parse(payload)
        observations = self.adapter.validate(parsed)
        if not observations:
            raise RuntimeError("Adapter returned no observations")
        keys = [item.target_key for item in observations]
        if len(keys) != len(set(keys)):
            raise RuntimeError("Adapter returned duplicate targets")
        return observations

    @staticmethod
    def _changed(
        previous: dict[str, Any] | None, observation: MonitorObservation
    ) -> bool:
        if previous is None:
            return False
        nested = previous.get("values")
        previous_values = nested if isinstance(nested, dict) else {}
        return any(
            (previous[key] if key in previous else previous_values.get(key)) != value
            for key, value in observation.comparison_values.items()
        )

    @staticmethod
    def _target_key(observation: MonitorObservation) -> str:
        return observation.target_key

    @staticmethod
    def _legacy_matches(
        current: dict[str, Any], observation: MonitorObservation
    ) -> bool:
        if current.get("target") == observation.target_key:
            return True
        return bool(
            current.get("level") == observation.group_key
            and current.get("session") == observation.target_label
        )

    @classmethod
    def _target_state(
        cls, state: dict[str, Any], observation: MonitorObservation
    ) -> dict[str, Any]:
        targets = state.setdefault("targets", {})
        key = observation.target_key
        if key not in targets:
            groups = state.get("levels", {})
            group_state = (
                groups.get(observation.group_key) if isinstance(groups, dict) else None
            )
            legacy_current = (
                group_state.get("current") if isinstance(group_state, dict) else None
            )
            legacy_previous = (
                group_state.get("previous") if isinstance(group_state, dict) else None
            )
            group_notifications = (
                group_state.get("notifications", {})
                if isinstance(group_state, dict)
                else {}
            )
            if not isinstance(legacy_current, dict):
                top_current = state.get("current")
                if isinstance(top_current, dict):
                    legacy_current = top_current
                    legacy_previous = state.get("previous")
                    group_notifications = state.get("notifications", {})
            migrate_legacy = bool(
                isinstance(legacy_current, dict)
                and cls._legacy_matches(legacy_current, observation)
            )
            targets[key] = {
                "previous": legacy_previous if migrate_legacy else None,
                "current": legacy_current if migrate_legacy else None,
                "notifications": {
                    "last_urgent_at": (
                        group_notifications.get("last_urgent_at")
                        if migrate_legacy
                        else None
                    ),
                    "last_urgent_remaining": (
                        group_notifications.get("last_urgent_remaining")
                        if migrate_legacy
                        else None
                    ),
                },
            }
        return cast(dict[str, Any], targets[key])

    @staticmethod
    def _numeric(value: Scalar) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value

    @staticmethod
    def _update_statistics(
        state: dict[str, Any],
        observations: tuple[MonitorObservation, ...],
        today: date,
    ) -> None:
        primary = observations[0]
        stats = state["statistics"]
        stats["checks_total"] += 1
        stats["successes"] += 1
        stats["consecutive_failures"] = 0
        stats["latency_total_ms"] += max(item.latency_ms for item in observations)
        stats["last_success_at"] = primary.checked_at.isoformat()
        daily = stats["daily"]
        if daily["date"] != today.isoformat():
            daily.update(
                {
                    "date": today.isoformat(),
                    "checks": 0,
                    "min_remaining": None,
                    "max_remaining": None,
                    "duration_total_ms": 0.0,
                    "latency_total_ms": 0.0,
                    "levels": {},
                }
            )
        daily["checks"] += 1
        daily["latency_total_ms"] += max(item.latency_ms for item in observations)
        primary_value = MonitorEngine._numeric(primary.current_value)
        if primary_value is not None:
            daily["min_remaining"] = (
                primary_value
                if daily["min_remaining"] is None
                else min(float(daily["min_remaining"]), primary_value)
            )
            daily["max_remaining"] = (
                primary_value
                if daily["max_remaining"] is None
                else max(float(daily["max_remaining"]), primary_value)
            )
        daily_targets = daily.setdefault("levels", {})
        for observation in observations:
            value = MonitorEngine._numeric(observation.current_value)
            if value is None:
                continue
            target_stats = daily_targets.setdefault(
                observation.target_key,
                {"min_remaining": None, "max_remaining": None},
            )
            target_stats["min_remaining"] = (
                value
                if target_stats["min_remaining"] is None
                else min(float(target_stats["min_remaining"]), value)
            )
            target_stats["max_remaining"] = (
                value
                if target_stats["max_remaining"] is None
                else max(float(target_stats["max_remaining"]), value)
            )

    @staticmethod
    def _urgent_kind(
        observation: MonitorObservation,
        observations: tuple[MonitorObservation, ...],
    ) -> str:
        if len(observations) == 1:
            return "urgent"
        group_count = sum(
            item.group_key == observation.group_key for item in observations
        )
        if group_count > 1:
            return f"urgent:{observation.group_key}:{observation.target_label}"
        return f"urgent:{observation.group_key}"

    @staticmethod
    def _previous_value(
        previous: dict[str, Any], observation: MonitorObservation
    ) -> object:
        if "remaining" in previous:
            return previous["remaining"]
        if "value" in previous:
            return previous["value"]
        values = previous.get("values")
        if isinstance(values, dict):
            for key, value in observation.comparison_values.items():
                if value == observation.current_value and key in values:
                    return values[key]
        return None

    def _send_urgent_alerts(
        self,
        state: dict[str, Any],
        observations: tuple[MonitorObservation, ...],
        sent: list[str],
    ) -> bool:
        changed_any = False
        for observation in observations:
            target_state = self._target_state(state, observation)
            previous = target_state.get("current")
            changed_any = self._changed(previous, observation) or changed_any
            target_state["previous"] = previous
            target_state["current"] = observation.to_dict()
            notifications = target_state["notifications"]
            value_changed = bool(
                previous is not None
                and self._previous_value(previous, observation)
                != observation.current_value
            )
            repeat_interval = getattr(
                self.settings, "available_alert_interval", self.settings.urgent_interval
            )
            repeat_enabled = getattr(self.settings, "repeat_available_alerts", True)
            urgent_due = _is_due(
                notifications["last_urgent_at"], observation.checked_at, repeat_interval
            )
            first_available = previous is None and observation.available
            if observation.available and (
                value_changed or first_available or (repeat_enabled and urgent_due)
            ):
                kind = self._urgent_kind(observation, observations)
                if self._send(
                    sent,
                    kind,
                    observations,
                    Priority.HIGH,
                    observation=observation,
                    state=state,
                    now=observation.checked_at,
                ):
                    notifications["last_urgent_at"] = observation.checked_at.isoformat()
                    notifications["last_urgent_remaining"] = observation.current_value
        return changed_any

    def run_once(self) -> MonitorResult[MonitorObservation]:
        started = time.monotonic()
        try:
            observations = self._fetch_observations()
        except Exception:
            self._record_failure(self.clock())
            LOGGER.exception("Website check failed")
            raise
        primary = observations[0]
        now = primary.checked_at
        sent: list[str] = []
        with self.store.transaction() as state:
            changed = self._send_urgent_alerts(state, observations, sent)
            groups = state.setdefault("levels", {})
            mirrored_groups: set[str] = set()
            for observation in observations:
                if observation.group_key not in mirrored_groups:
                    groups[observation.group_key] = self._target_state(
                        state, observation
                    )
                    mirrored_groups.add(observation.group_key)
            primary_state = self._target_state(state, primary)
            state["previous"] = primary_state["previous"]
            state["current"] = primary_state["current"]
            self._update_statistics(state, observations, now.date())
            notifications = state["notifications"]

            quiet_heartbeat = getattr(self.settings, "quiet_heartbeat", False)
            heartbeat_allowed = not quiet_heartbeat or all(
                item.current_value == 0 for item in observations
            )
            if (
                heartbeat_allowed
                and _is_due(
                    notifications["last_heartbeat_at"],
                    now,
                    self.settings.heartbeat_interval,
                )
                and self._send(
                    sent,
                    "heartbeat",
                    observations,
                    Priority.LOW,
                    state=state,
                    now=now,
                )
            ):
                notifications["last_heartbeat_at"] = now.isoformat()

            daily_due = (
                self.settings.enable_daily_summary
                and now.hour >= self.settings.daily_summary_hour
                and notifications["last_daily_summary_date"] != now.date().isoformat()
            )
            if daily_due and self._send(
                sent,
                "daily_summary",
                observations,
                Priority.NORMAL,
                daily_statistics=state["statistics"]["daily"],
                state=state,
                now=now,
            ):
                notifications["last_daily_summary_date"] = now.date().isoformat()

            primary_target_notifications = primary_state["notifications"]
            notifications["last_urgent_at"] = primary_target_notifications[
                "last_urgent_at"
            ]
            notifications["last_urgent_remaining"] = primary_target_notifications[
                "last_urgent_remaining"
            ]

            duration_ms = (time.monotonic() - started) * 1000
            state["statistics"]["duration_total_ms"] += duration_ms
            state["statistics"]["daily"]["duration_total_ms"] += duration_ms
            record_execution(
                state,
                observations,
                duration_ms,
                sent,
                self.settings.history_retention_days,
            )
            try:
                write_history_files(state, self.settings.data_dir)
            except OSError:
                LOGGER.exception("Could not materialize history JSON and CSV files")

        LOGGER.info(
            "Website check completed",
            extra={
                "adapter": self.settings.adapter,
                "targets": [item.target_key for item in observations],
                "values": {
                    item.target_key: item.current_value for item in observations
                },
                "changed": changed,
                "duration_ms": round(duration_ms, 2),
                "latency_ms": max(item.latency_ms for item in observations),
                "fetch_method": primary.fetch_method,
                "notifications": sent,
            },
        )
        return MonitorResult(
            primary,
            changed,
            tuple(sent),
            round(duration_ms, 2),
            observations,
        )


class MonitorService(MonitorEngine):
    """Backward-compatible name for the generic monitor engine."""

    def __init__(
        self,
        settings: Settings,
        *,
        adapter: WebsiteAdapter[Any] | None = None,
        scraper: object | None = None,
        notifier: Notifier | None = None,
        store: StateStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if adapter is not None and scraper is not None:
            raise ValueError("scraper cannot be combined with an explicit adapter")
        selected = adapter
        if scraper is not None:
            selected = WebsiteAdapter.create(settings)
            if not hasattr(selected, "scraper"):
                raise ValueError("selected adapter does not expose a legacy scraper")
            cast(Any, selected).scraper = scraper
        super().__init__(
            settings,
            adapter=selected,
            notifier=notifier,
            store=store,
            clock=clock,
        )
        self.scraper = getattr(self.adapter, "scraper", None)
