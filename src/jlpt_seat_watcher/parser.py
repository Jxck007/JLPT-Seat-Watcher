"""Resilient parser for the JLPT examination application counters."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


class ParserError(ValueError):
    """Raised when a safe N4 observation cannot be extracted."""


@dataclass(frozen=True, slots=True)
class ParsedSeat:
    session: str
    level: str
    total: int
    applied: int
    remaining: int
    structure_changed: bool


_LEVEL_RE = re.compile(r"\b(N[1-5])\s+Total\s*:\s*([\d,]+)\b", re.IGNORECASE)
_APPLIED_RE = re.compile(r"\bApplied\s*:\s*([\d,]+)\b", re.IGNORECASE)
_REMAINING_RE = re.compile(r"\bRemaining\s*:\s*([\d,]+)\b", re.IGNORECASE)
_N4_MARKER_RE = re.compile(r"\bN4\s+Total\s*:", re.IGNORECASE)


def _number(raw: str, label: str) -> int:
    try:
        value = int(raw.replace(",", ""))
    except ValueError as exc:
        raise ParserError(f"{label} is not an integer") from exc
    if value < 0:
        raise ParserError(f"{label} cannot be negative")
    return value


def _validate(total: int, applied: int, remaining: int) -> None:
    if total <= 0:
        raise ParserError("N4 total must be positive")
    if applied > total or remaining > total:
        raise ParserError("N4 applied or remaining exceeds total")
    if applied + remaining != total:
        raise ParserError("N4 counters do not satisfy total = applied + remaining")


def _from_cells(soup: BeautifulSoup) -> ParsedSeat:
    cells = soup.select(".table-container1 .cell1")
    if not cells:
        raise ParserError("Expected examination table cells are missing")
    session = ""
    candidates: list[tuple[str, int, int, int]] = []
    index = 0
    while index < len(cells):
        text = cells[index].get_text(" ", strip=True)
        upper = text.upper()
        if "FORENOON EXAM APPLICATIONS" in upper:
            session = "Forenoon"
            index += 1
            continue
        if "AFTERNOON EXAM APPLICATIONS" in upper:
            session = "Afternoon"
            index += 1
            continue
        level_match = _LEVEL_RE.search(text)
        if level_match and level_match.group(1).upper() == "N4":
            if index + 2 >= len(cells):
                raise ParserError("N4 row is incomplete")
            applied_match = _APPLIED_RE.search(
                cells[index + 1].get_text(" ", strip=True)
            )
            remaining_match = _REMAINING_RE.search(
                cells[index + 2].get_text(" ", strip=True)
            )
            if not applied_match or not remaining_match:
                raise ParserError("N4 applied or remaining cell is malformed")
            candidates.append(
                (
                    session,
                    _number(level_match.group(2), "total"),
                    _number(applied_match.group(1), "applied"),
                    _number(remaining_match.group(1), "remaining"),
                )
            )
            index += 3
            continue
        index += 1
    if len(candidates) != 1:
        raise ParserError(f"Expected exactly one N4 row; found {len(candidates)}")
    parsed_session, total, applied, remaining = candidates[0]
    if parsed_session != "Afternoon":
        raise ParserError("N4 is not located in the Afternoon section")
    _validate(total, applied, remaining)
    return ParsedSeat(parsed_session, "N4", total, applied, remaining, False)


def _semantic_fallback(soup: BeautifulSoup) -> ParsedSeat:
    text = " ".join(soup.stripped_strings)
    markers = list(_N4_MARKER_RE.finditer(text))
    if len(markers) != 1:
        raise ParserError(
            f"Expected exactly one semantic N4 marker; found {len(markers)}"
        )
    afternoon = text.upper().rfind("AFTERNOON EXAM APPLICATIONS", 0, markers[0].start())
    forenoon = text.upper().rfind("FORENOON EXAM APPLICATIONS", 0, markers[0].start())
    if afternoon < 0 or afternoon < forenoon:
        raise ParserError("Semantic N4 marker is not in the Afternoon section")
    segment = text[markers[0].start() : markers[0].start() + 300]
    level_match = _LEVEL_RE.search(segment)
    applied_match = _APPLIED_RE.search(segment)
    remaining_match = _REMAINING_RE.search(segment)
    if not level_match or not applied_match or not remaining_match:
        raise ParserError("Semantic N4 counters are incomplete or malformed")
    total = _number(level_match.group(2), "total")
    applied = _number(applied_match.group(1), "applied")
    remaining = _number(remaining_match.group(1), "remaining")
    _validate(total, applied, remaining)
    return ParsedSeat("Afternoon", "N4", total, applied, remaining, True)


def parse_n4(html: str) -> ParsedSeat:
    """Parse and validate N4 counters, with a structure-change fallback."""

    if not html.strip():
        raise ParserError("Website returned empty HTML")
    soup = BeautifulSoup(html, "html.parser")
    try:
        return _from_cells(soup)
    except ParserError as primary_error:
        try:
            return _semantic_fallback(soup)
        except ParserError as fallback_error:
            message = (
                f"Primary parser failed ({primary_error}); "
                f"fallback failed ({fallback_error})"
            )
            raise ParserError(message) from fallback_error
