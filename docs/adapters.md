# Adapter development

Watchtower keeps website-specific code outside the core monitoring engine. A
built-in adapter is one class under `watchtower/adapters/` with a unique `name`
and four required methods.

## Contract

```python
from watchtower.adapters import NotificationEvent, WebsiteAdapter
from watchtower.models import WebsiteObservation
from watchtower.notifier import Notifier


class ExampleAdapter(WebsiteAdapter[WebsiteObservation]):
    name = "example"

    def fetch(self) -> object:
        """Retrieve raw website data and return any adapter-owned payload."""
        ...

    def parse(self, payload: object) -> tuple[WebsiteObservation, ...]:
        """Convert the fetched payload into standard observations."""
        ...

    def validate(
        self, observations: tuple[WebsiteObservation, ...]
    ) -> tuple[WebsiteObservation, ...]:
        """Reject incomplete, ambiguous, or unsafe observations."""
        ...

    def notify(
        self,
        event: NotificationEvent[WebsiteObservation],
        notifier: Notifier,
    ) -> None:
        """Format the domain message and deliver it with the notifier."""
        ...
```

No engine change or registry edit is required. Adapter modules are imported
automatically, and subclasses register their `name` when imported.

## Observation model

Use `WebsiteObservation` unless the adapter needs a richer domain model. Every
validated observation supplies:

- `target`: stable identifier used for state and alert deduplication.
- `value`: primary value used to detect urgent changes.
- `available`: whether the urgent alert cadence applies.
- `values`: fields compared to detect any state change.
- `checked_at`, `latency_ms`, and `fetch_method`: execution metadata.
- Optional `group` and `label`: notification and status display grouping.

When using a custom observation class, implement the `MonitorObservation`
protocol from `watchtower.models`.

## Notification events

The engine calls `notify()` only when an alert is due. `event.kind` is
`urgent` (possibly suffixed with a target), `heartbeat`, or `daily_summary`.
The event includes all current observations, the urgent observation when
applicable, priority, and daily statistics. Call the supplied notifier's
`send()` method so delivery retries and provider selection remain centralized.

## Selection

Select the adapter in `config.yaml`:

```yaml
adapter: example
website_url: https://example.com/status
```

`WATCHTOWER_ADAPTER` can override the YAML value. `jlpt_chennai` remains the
default when neither setting is supplied.

## Compatibility

The old `jlpt_seat_watcher` package is a facade over `watchtower`. Existing
imports such as `jlpt_seat_watcher.monitor.MonitorService`, parser and scraper
imports, `python -m jlpt_seat_watcher`, and the `jlpt-seat-watcher` console
script continue to resolve to the canonical implementation.
