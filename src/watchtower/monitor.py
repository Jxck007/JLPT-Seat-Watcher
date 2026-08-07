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
                    "last_high_alert_at": (
                        group_notifications.get("last_high_alert_at")
                        or group_notifications.get("last_urgent_at")
                        if migrate_legacy
                        else None
                    ),
                    "last_high_alert_remaining": (
                        group_notifications.get("last_high_alert_remaining")
                        if group_notifications.get("last_high_alert_remaining")
                        is not None
                        else (
                            group_notifications.get("last_urgent_remaining")
                            if migrate_legacy
                            else None
                        )
                    ),
                    "availability_started_at": (
                        group_notifications.get("availability_started_at")
                        if migrate_legacy
                        else None
                    ),
                    "last_max_alert_at": (
                        group_notifications.get("last_max_alert_at")
                        if migrate_legacy
                        else None
                    ),
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
    def _notification_kind(
        base: str,
        observation: MonitorObservation,
        observations: tuple[MonitorObservation, ...],
    ) -> str:
        if len(observations) == 1:
            return base
        group_count = sum(
            item.group_key == observation.group_key for item in observations
        )
        if group_count > 1:
            return f"{base}:{observation.group_key}:{observation.target_label}"
        return f"{base}:{observation.group_key}"

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

    def _select_availability_notification(
        self,
        state: dict[str, Any],
        observations: tuple[MonitorObservation, ...],
    ) -> tuple[
        bool,
        tuple[str, MonitorObservation, dict[str, Any], Priority] | None,
    ]:
        changed_any = False
        high_candidates: list[tuple[MonitorObservation, dict[str, Any]]] = []
        max_candidates: list[tuple[MonitorObservation, dict[str, Any]]] = []
        max_interval = getattr(self.settings, "max_alert_interval", 21600)
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
            if not observation.available:
                notifications["availability_started_at"] = None
                notifications["last_max_alert_at"] = None
                notifications["last_high_alert_remaining"] = None
                continue

            if notifications.get("availability_started_at") is None:
                notifications["availability_started_at"] = (
                    observation.checked_at.isoformat()
                )
            availability_started = _parse_time(
                notifications.get("availability_started_at")
            )
            max_due = bool(
                availability_started
                and observation.checked_at - availability_started
                >= timedelta(seconds=max_interval)
                and _is_due(
                    notifications.get("last_max_alert_at"),
                    observation.checked_at,
                    max_interval,
                )
            )
            if max_due:
                max_candidates.append((observation, notifications))

            last_high_remaining = notifications.get("last_high_alert_remaining")
            if value_changed or last_high_remaining != observation.current_value:
                high_candidates.append((observation, notifications))

        candidates = max_candidates or high_candidates
        if not candidates:
            return changed_any, None
        observation, notifications = candidates[0]
        priority = Priority.MAX if max_candidates else Priority.HIGH
        kind = self._notification_kind(
            "max" if max_candidates else "high", observation, observations
        )
        return changed_any, (kind, observation, notifications, priority)

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
            changed, availability_event = self._select_availability_notification(
                state, observations
            )
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
            state["last_check"] = now.isoformat()
            self._update_statistics(state, observations, now.date())
            notifications = state["notifications"]

            notification_selected = availability_event is not None
            if availability_event is not None:
                kind, event_observation, target_notifications, priority = (
                    availability_event
                )
                delivered = self._send(
                    sent,
                    kind,
                    observations,
                    priority,
                    observation=event_observation,
                    state=state,
                    now=now,
                )
                if delivered and priority == Priority.MAX:
                    target_notifications["last_max_alert_at"] = now.isoformat()
                    target_notifications["last_high_alert_remaining"] = (
                        event_observation.current_value
                    )
                elif delivered:
                    target_notifications["last_high_alert_at"] = now.isoformat()
                    target_notifications["last_high_alert_remaining"] = (
                        event_observation.current_value
                    )
                    target_notifications["last_urgent_at"] = now.isoformat()
                    target_notifications["last_urgent_remaining"] = (
                        event_observation.current_value
                    )
                if delivered:
                    notifications["last_status_notification_at"] = now.isoformat()
                    if notifications["notification_cadence_started_at"] is None:
                        notifications["notification_cadence_started_at"] = (
                            now.isoformat()
                        )

            if not notification_selected and _is_due(
                notifications["last_status_notification_at"],
                now,
                self.settings.check_interval,
            ):
                default_anchor = (
                    notifications["last_default_notification_at"]
                    or notifications["notification_cadence_started_at"]
                )
                default_due = default_anchor is not None and _is_due(
                    default_anchor, now, self.settings.heartbeat_interval
                )
                kind = "default" if default_due else "min"
                priority = Priority.DEFAULT if default_due else Priority.MIN
                if self._send(
                    sent,
                    kind,
                    observations,
                    priority,
                    state=state,
                    now=now,
                ):
                    notifications["last_status_notification_at"] = now.isoformat()
                    if notifications["notification_cadence_started_at"] is None:
                        notifications["notification_cadence_started_at"] = (
                            now.isoformat()
                        )
                    if default_due:
                        notifications["last_default_notification_at"] = now.isoformat()
                        notifications["last_heartbeat_at"] = now.isoformat()
                    else:
                        notifications["last_min_notification_at"] = now.isoformat()

            primary_target_notifications = primary_state["notifications"]
            for key in (
                "last_high_alert_at",
                "last_high_alert_remaining",
                "availability_started_at",
                "last_max_alert_at",
                "last_urgent_at",
                "last_urgent_remaining",
            ):
                notifications[key] = primary_target_notifications.get(key)

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
