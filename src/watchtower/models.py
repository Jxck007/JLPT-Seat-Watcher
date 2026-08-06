"""Typed domain models used by scraping and monitoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

type Scalar = str | int | float | bool | None


@runtime_checkable
class MonitorObservation(Protocol):
    """The domain-neutral observation interface consumed by the core engine."""

    @property
    def checked_at(self) -> datetime: ...

    @property
    def latency_ms(self) -> float: ...

    @property
    def fetch_method(self) -> str: ...

    @property
    def structure_changed(self) -> bool: ...

    @property
    def target_key(self) -> str: ...

    @property
    def group_key(self) -> str: ...

    @property
    def target_label(self) -> str: ...

    @property
    def available(self) -> bool: ...

    @property
    def current_value(self) -> Scalar: ...

    @property
    def comparison_values(self) -> dict[str, Scalar]: ...

    def to_dict(self) -> dict[str, Any]: ...

    def to_history_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class WebsiteObservation:
    """Generic observation available to future website adapters."""

    target: str
    value: Scalar
    available: bool
    checked_at: datetime
    latency_ms: float
    fetch_method: str
    values: dict[str, Scalar]
    group: str = ""
    label: str = ""
    structure_changed: bool = False

    @property
    def target_key(self) -> str:
        return self.target

    @property
    def group_key(self) -> str:
        return self.group or self.target

    @property
    def target_label(self) -> str:
        return self.label or self.target

    @property
    def current_value(self) -> Scalar:
        return self.value

    @property
    def comparison_values(self) -> dict[str, Scalar]:
        return self.values

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "group": self.group_key,
            "label": self.target_label,
            "value": self.value,
            "available": self.available,
            "values": self.values,
            "checked_at": self.checked_at.isoformat(),
            "latency_ms": self.latency_ms,
            "fetch_method": self.fetch_method,
            "structure_changed": self.structure_changed,
        }

    def to_history_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "group": self.group_key,
            "label": self.target_label,
            "value": self.value,
            "available": self.available,
            "values": self.values,
        }


@dataclass(frozen=True, slots=True)
class SeatObservation:
    """A validated snapshot of one JLPT level's application counters."""

    session: str
    level: str
    total: int
    applied: int
    remaining: int
    checked_at: datetime
    latency_ms: float
    fetch_method: str
    structure_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["checked_at"] = self.checked_at.isoformat()
        return value

    @property
    def target_key(self) -> str:
        return f"{self.level}:{self.session}"

    @property
    def group_key(self) -> str:
        return self.level

    @property
    def target_label(self) -> str:
        return self.session

    @property
    def available(self) -> bool:
        return self.remaining > 0

    @property
    def current_value(self) -> Scalar:
        return self.remaining

    @property
    def comparison_values(self) -> dict[str, Scalar]:
        return {
            "session": self.session,
            "total": self.total,
            "applied": self.applied,
            "remaining": self.remaining,
        }

    def to_history_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "session": self.session,
            "remaining": self.remaining,
            "applied": self.applied,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SeatObservation:
        return cls(
            session=str(value["session"]),
            level=str(value["level"]),
            total=int(value["total"]),
            applied=int(value["applied"]),
            remaining=int(value["remaining"]),
            checked_at=datetime.fromisoformat(str(value["checked_at"])),
            latency_ms=float(value["latency_ms"]),
            fetch_method=str(value["fetch_method"]),
            structure_changed=bool(value.get("structure_changed", False)),
        )


@dataclass(frozen=True, slots=True)
class MonitorResult[ObservationT: MonitorObservation]:
    """Summary returned by one complete monitor cycle."""

    observation: ObservationT
    changed: bool
    notifications: tuple[str, ...]
    duration_ms: float
    observations: tuple[ObservationT, ...] = ()

    @property
    def all_observations(self) -> tuple[ObservationT, ...]:
        """Return every observation while preserving the legacy singular field."""

        return self.observations or (self.observation,)


CheckResult = MonitorResult[SeatObservation]
