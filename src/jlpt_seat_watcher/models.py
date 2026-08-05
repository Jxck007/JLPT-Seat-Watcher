"""Typed domain models used by scraping and monitoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class SeatObservation:
    """A validated snapshot of the N4 application counters."""

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
class CheckResult:
    """Summary returned by one complete monitor cycle."""

    observation: SeatObservation
    changed: bool
    notifications: tuple[str, ...]
    duration_ms: float
