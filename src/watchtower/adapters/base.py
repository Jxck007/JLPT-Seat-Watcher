"""Adapter contract between website-specific integrations and the core engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import import_module
from pkgutil import iter_modules
from typing import Any, ClassVar

from watchtower.config import Settings
from watchtower.models import MonitorObservation
from watchtower.notifier import Notifier, Priority


@dataclass(frozen=True, slots=True)
class NotificationEvent[ObservationT: MonitorObservation]:
    """A transport-independent notification request from the core engine."""

    kind: str
    observations: tuple[ObservationT, ...]
    observation: ObservationT | None
    priority: Priority
    daily_statistics: dict[str, Any] | None = None


class WebsiteAdapter[ObservationT: MonitorObservation](ABC):
    """Self-registering website adapter with four required operations."""

    name: ClassVar[str] = ""
    _adapters: ClassVar[dict[str, type[WebsiteAdapter[Any]]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        name = getattr(cls, "name", "").strip().casefold()
        if name:
            WebsiteAdapter._adapters[name] = cls

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    def create(cls, settings: Settings) -> WebsiteAdapter[Any]:
        package = import_module("watchtower.adapters")
        for module in iter_modules(package.__path__):
            if module.name not in {"base", "__init__"}:
                import_module(f"watchtower.adapters.{module.name}")
        name = settings.adapter.strip().casefold()
        adapter_class = cls._adapters.get(name)
        if adapter_class is None:
            available = ", ".join(sorted(cls._adapters))
            raise ValueError(
                f"Unknown website adapter '{name}'. Available: {available}"
            )
        return adapter_class(settings)

    @abstractmethod
    def fetch(self) -> object:
        """Retrieve website-specific source data."""

    @abstractmethod
    def parse(self, payload: object) -> tuple[ObservationT, ...]:
        """Convert fetched data into standard monitor observations."""

    @abstractmethod
    def validate(
        self, observations: tuple[ObservationT, ...]
    ) -> tuple[ObservationT, ...]:
        """Reject incomplete, ambiguous, or unsafe observations."""

    @abstractmethod
    def notify(
        self, event: NotificationEvent[ObservationT], notifier: Notifier
    ) -> None:
        """Format and deliver one website-specific notification."""
