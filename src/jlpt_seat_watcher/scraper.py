"""Static-first scraper with an automatic Playwright fallback."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from jlpt_seat_watcher.config import Settings
from jlpt_seat_watcher.models import SeatObservation
from jlpt_seat_watcher.parser import ParsedSeat, ParserError, parse_n4

LOGGER = logging.getLogger(__name__)

USER_AGENTS = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) "
    "Gecko/20100101 Firefox/136.0",
)
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ScraperError(RuntimeError):
    """Raised after both static and rendered scraping paths fail."""


class Scraper:
    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_source: random.Random | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.sleep = sleep
        self.random = random_source or random.Random()
        self.now = now or (lambda: datetime.now(settings.timezone))
        self.snapshot_dir = settings.logs_dir / "snapshots"

    def _artifact_path(self, suffix: str) -> Path:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.now().strftime("%Y%m%dT%H%M%S%f%z")
        return self.snapshot_dir / f"failure-{stamp}-{uuid4().hex[:8]}.{suffix}"

    def _save_html(self, html: str, reason: str) -> Path | None:
        if not html:
            return None
        path = self._artifact_path("html")
        path.write_text(f"<!-- {reason} -->\n{html}", encoding="utf-8")
        LOGGER.warning("Saved diagnostic HTML", extra={"artifact": str(path)})
        return path

    def _backoff(self, attempt: int) -> float:
        return float(min(30.0, (2 ** (attempt - 1)) + self.random.uniform(0.0, 0.5)))

    def _request_html(self) -> tuple[str, float]:
        last_error: Exception | None = None
        last_html = ""
        for attempt in range(1, self.settings.max_retries + 1):
            started = time.monotonic()
            try:
                response = self.session.get(
                    self.settings.website_url,
                    headers={"User-Agent": self.random.choice(USER_AGENTS)},
                    timeout=self.settings.scraper_timeout,
                )
                last_html = response.text
                if response.status_code in RETRYABLE_STATUS:
                    raise requests.HTTPError(f"retryable HTTP {response.status_code}")
                response.raise_for_status()
                return response.text, (time.monotonic() - started) * 1000
            except requests.RequestException as exc:
                last_error = exc
                LOGGER.warning(
                    "Static fetch attempt failed",
                    extra={"attempt": attempt, "error_type": type(exc).__name__},
                )
                if attempt < self.settings.max_retries:
                    self.sleep(self._backoff(attempt))
        self._save_html(last_html, "Static HTTP retrieval failed")
        raise ScraperError(
            f"Static fetch failed after {self.settings.max_retries} attempts"
        ) from last_error

    def _rendered(self) -> tuple[ParsedSeat, float]:
        started = time.monotonic()
        html = ""
        browser: Any = None
        page: Any = None
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.random.choice(USER_AGENTS))
                page.goto(
                    self.settings.website_url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.scraper_timeout * 1000,
                )
                page.wait_for_timeout(1000)
                html = page.content()
                parsed = parse_n4(html)
                browser.close()
                return parsed, (time.monotonic() - started) * 1000
        except Exception as exc:
            self._save_html(html, "Rendered retrieval or parsing failed")
            if self.settings.enable_screenshot and page is not None:
                try:
                    screenshot = self._artifact_path("png")
                    page.screenshot(path=str(screenshot), full_page=True)
                    LOGGER.warning(
                        "Saved diagnostic screenshot",
                        extra={"artifact": str(screenshot)},
                    )
                except Exception:
                    LOGGER.exception("Could not save diagnostic screenshot")
            if browser is not None:
                with suppress(Exception):
                    browser.close()
            raise ScraperError("Playwright fallback failed") from exc

    def fetch(self) -> SeatObservation:
        """Fetch and parse one observation, using rendering only when needed."""

        static_html = ""
        try:
            static_html, latency_ms = self._request_html()
            parsed = parse_n4(static_html)
            method = "requests"
            if parsed.structure_changed:
                self._save_html(
                    static_html, "Website structure changed; fallback parsed"
                )
        except (ScraperError, ParserError) as static_error:
            if static_html:
                self._save_html(static_html, f"Static parser failed: {static_error}")
            if not self.settings.enable_playwright:
                raise ScraperError(
                    "Static scraping failed and Playwright fallback is disabled"
                ) from static_error
            LOGGER.warning(
                "Using Playwright fallback", extra={"reason": str(static_error)}
            )
            parsed, latency_ms = self._rendered()
            method = "playwright"
        return SeatObservation(
            session=parsed.session,
            level=parsed.level,
            total=parsed.total,
            applied=parsed.applied,
            remaining=parsed.remaining,
            checked_at=self.now(),
            latency_ms=round(latency_ms, 2),
            fetch_method=method,
            structure_changed=parsed.structure_changed,
        )
