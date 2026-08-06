"""Console and rotating structured file logging."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, ClassVar


class JsonFormatter(logging.Formatter):
    """Emit stable JSON lines while preserving structured extras."""

    _standard: ClassVar[set[str]] = set(
        logging.LogRecord("", 0, "", 0, "", (), None).__dict__
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._standard and key not in {"message", "asctime"}:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(log_dir: Path, level: str) -> None:
    """Configure idempotent console and file handlers."""

    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    root.addHandler(console)

    structured = RotatingFileHandler(
        log_dir / "monitor.jsonl", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    structured.setLevel(level)
    structured.setFormatter(JsonFormatter())
    root.addHandler(structured)
