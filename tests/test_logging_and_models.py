from __future__ import annotations

import json
import logging
from datetime import datetime

from jlpt_seat_watcher.config import Settings
from jlpt_seat_watcher.logging_setup import JsonFormatter, configure_logging
from jlpt_seat_watcher.models import SeatObservation


def test_observation_round_trip(settings: Settings) -> None:
    original = SeatObservation(
        "Afternoon",
        "N4",
        850,
        849,
        1,
        datetime.now(settings.timezone),
        10.5,
        "requests",
        True,
    )
    assert SeatObservation.from_dict(original.to_dict()) == original


def test_json_formatter_and_logging_configuration(settings: Settings) -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord("watcher", logging.INFO, __file__, 1, "ready", (), None)
    record.remaining = 0
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "ready"
    assert payload["remaining"] == 0

    configure_logging(settings.logs_dir, "INFO")
    logging.getLogger("watcher").info("configured")
    contents = (settings.logs_dir / "monitor.jsonl").read_text(encoding="utf-8")
    assert '"message": "configured"' in contents
