"""Default adapter for the JLPT Chennai seat counter website."""

from __future__ import annotations

from typing import cast

from watchtower.adapters.base import NotificationEvent, WebsiteAdapter
from watchtower.adapters.jlpt_chennai.scraper import Scraper
from watchtower.config import Settings
from watchtower.models import SeatObservation
from watchtower.notifier import Notifier, Priority


def _notification_body(observation: SeatObservation, website_url: str) -> str:
    return "\n".join(
        (
            f"Level: {observation.level}",
            f"Session: {observation.session}",
            f"Remaining: {observation.remaining}",
            f"Applied: {observation.applied}",
            f"Total: {observation.total}",
            f"Website: {website_url}",
            f"Timestamp: {observation.checked_at.isoformat()}",
        )
    )


class JlptChennaiAdapter(WebsiteAdapter[SeatObservation]):
    """Preserve JLPT Chennai scraping and alert behavior behind the adapter API."""

    name = "jlpt_chennai"

    def __init__(self, settings: Settings, *, scraper: object | None = None) -> None:
        super().__init__(settings)
        self.scraper = scraper or Scraper(settings)

    def fetch(self) -> object:
        fetch_all = getattr(self.scraper, "fetch_all", None)
        if callable(fetch_all):
            return tuple(fetch_all())
        fetch_one = getattr(self.scraper, "fetch", None)
        if not callable(fetch_one):
            raise RuntimeError("JLPT scraper does not provide fetch()")
        return (fetch_one(),)

    def parse(self, payload: object) -> tuple[SeatObservation, ...]:
        if not isinstance(payload, tuple):
            raise RuntimeError("JLPT adapter expected a tuple of observations")
        if not all(isinstance(item, SeatObservation) for item in payload):
            raise RuntimeError("JLPT adapter received an invalid observation")
        return cast(tuple[SeatObservation, ...], payload)

    def validate(
        self, observations: tuple[SeatObservation, ...]
    ) -> tuple[SeatObservation, ...]:
        if not observations:
            raise RuntimeError("JLPT scraper returned no observations")
        keys = [item.target_key for item in observations]
        if len(keys) != len(set(keys)):
            raise RuntimeError("JLPT scraper returned duplicate level/session targets")
        for observation in observations:
            if (
                min(
                    observation.total,
                    observation.applied,
                    observation.remaining,
                )
                < 0
            ):
                raise RuntimeError("JLPT scraper returned a negative seat counter")
            if observation.total != observation.applied + observation.remaining:
                raise RuntimeError("JLPT seat counters failed validation")
        return observations

    def _aggregate_body(self, observations: tuple[SeatObservation, ...]) -> str:
        return "\n\n".join(
            _notification_body(observation, self.settings.website_url)
            for observation in observations
        )

    def notify(
        self, event: NotificationEvent[SeatObservation], notifier: Notifier
    ) -> None:
        if event.kind.startswith("urgent"):
            if event.observation is None:
                raise ValueError("Urgent JLPT notification requires an observation")
            observation = event.observation
            notifier.send(
                f"JLPT {observation.level} SEATS AVAILABLE",
                _notification_body(observation, self.settings.website_url),
                event.priority,
                tags=("rotating_light", "jlpt", observation.level.lower()),
            )
            return

        if event.kind == "heartbeat":
            notifier.send(
                "JLPT Monitor Running",
                self._aggregate_body(event.observations),
                Priority.SILENT,
                tags=("white_check_mark", "jlpt"),
            )
            return

        if event.kind == "daily_summary":
            daily = event.daily_statistics or {}
            checks = max(int(daily.get("checks", 0)), 1)
            latency = float(daily.get("latency_total_ms", 0.0)) / checks
            body = (
                f"Checks today: {daily.get('checks', 0)}\n"
                f"Average website latency: {latency:.0f} ms\n\n"
                f"{self._aggregate_body(event.observations)}"
            )
            notifier.send(
                "JLPT Monitor Daily Summary",
                body,
                Priority.NORMAL,
                tags=("bar_chart", "jlpt"),
            )
            return
        raise ValueError(f"Unsupported JLPT notification event: {event.kind}")
