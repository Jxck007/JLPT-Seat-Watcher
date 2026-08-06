"""Resilient parser for JLPT examination application counters."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from watchtower.config import SUPPORTED_LEVELS, SUPPORTED_SESSION_MODES


class ParserError(ValueError):
    """Raised when requested seat observations cannot be extracted safely."""


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
_SESSION_MARKERS = {
    "Forenoon": "FORENOON EXAM APPLICATIONS",
    "Afternoon": "AFTERNOON EXAM APPLICATIONS",
}


def _normalize_levels(levels: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = tuple(str(level).strip().upper() for level in levels)
    if not normalized:
        raise ParserError("At least one JLPT level must be requested")
    if any(level not in SUPPORTED_LEVELS for level in normalized):
        raise ParserError("Requested JLPT level is not supported")
    if len(set(normalized)) != len(normalized):
        raise ParserError("Requested JLPT levels cannot contain duplicates")
    return normalized


def _normalize_session_mode(session_mode: str) -> str:
    modes = {mode.casefold(): mode for mode in SUPPORTED_SESSION_MODES}
    normalized = str(session_mode).strip().casefold()
    if normalized not in modes:
        raise ParserError("Requested session mode is not supported")
    return modes[normalized]


def _number(raw: str, level: str, label: str) -> int:
    try:
        value = int(raw.replace(",", ""))
    except ValueError as exc:
        raise ParserError(f"{level} {label} is not an integer") from exc
    if value < 0:
        raise ParserError(f"{level} {label} cannot be negative")
    return value


def _validate_counters(level: str, total: int, applied: int, remaining: int) -> None:
    if total <= 0:
        raise ParserError(f"{level} total must be positive")
    if applied > total or remaining > total:
        raise ParserError(f"{level} applied or remaining exceeds total")
    if applied + remaining != total:
        raise ParserError(
            f"{level} counters do not satisfy total = applied + remaining"
        )


def _select_candidates(
    candidates: dict[str, list[ParsedSeat]],
    levels: tuple[str, ...],
    session_mode: str,
    source: str,
) -> tuple[ParsedSeat, ...]:
    selected: list[ParsedSeat] = []
    for level in levels:
        level_candidates = candidates[level]
        descriptor = (
            f"semantic {level} marker"
            if source == "semantic marker"
            else f"{level} row"
        )
        if session_mode == "Auto":
            if len(level_candidates) != 1:
                raise ParserError(
                    f"Expected exactly one {descriptor} in Auto mode; "
                    f"found {len(level_candidates)}"
                )
            selected.append(level_candidates[0])
            continue
        if session_mode in _SESSION_MARKERS:
            matching = [
                item for item in level_candidates if item.session == session_mode
            ]
            if not matching and level_candidates:
                raise ParserError(f"{level} is not in the {session_mode} section")
            if len(matching) != 1:
                raise ParserError(
                    f"Expected exactly one {descriptor} in {session_mode}; "
                    f"found {len(matching)}"
                )
            selected.append(matching[0])
            continue

        for session in _SESSION_MARKERS:
            matching = [item for item in level_candidates if item.session == session]
            if len(matching) > 1:
                raise ParserError(
                    f"Expected at most one {descriptor} in {session}; "
                    f"found {len(matching)}"
                )
            selected.extend(matching)
        if not any(item.level == level for item in selected):
            raise ParserError(f"No {descriptor} found in either session")
    return tuple(selected)


def _from_cells(
    soup: BeautifulSoup, levels: tuple[str, ...], session_mode: str
) -> tuple[ParsedSeat, ...]:
    cells = soup.select(".table-container1 .cell1")
    if not cells:
        raise ParserError("Expected examination table cells are missing")
    requested = set(levels)
    candidates: dict[str, list[ParsedSeat]] = {level: [] for level in levels}
    session = ""
    index = 0
    while index < len(cells):
        text = cells[index].get_text(" ", strip=True)
        upper = text.upper()
        matched_session = next(
            (name for name, marker in _SESSION_MARKERS.items() if marker in upper),
            None,
        )
        if matched_session:
            session = matched_session
            index += 1
            continue
        level_match = _LEVEL_RE.search(text)
        level = level_match.group(1).upper() if level_match else ""
        if level_match and level in requested:
            if not session:
                raise ParserError(f"{level} row has no session section")
            if index + 2 >= len(cells):
                raise ParserError(f"{level} row is incomplete")
            applied_match = _APPLIED_RE.search(
                cells[index + 1].get_text(" ", strip=True)
            )
            remaining_match = _REMAINING_RE.search(
                cells[index + 2].get_text(" ", strip=True)
            )
            if not applied_match or not remaining_match:
                raise ParserError(f"{level} applied or remaining cell is malformed")
            total = _number(level_match.group(2), level, "total")
            applied = _number(applied_match.group(1), level, "applied")
            remaining = _number(remaining_match.group(1), level, "remaining")
            _validate_counters(level, total, applied, remaining)
            candidates[level].append(
                ParsedSeat(session, level, total, applied, remaining, False)
            )
            index += 3
            continue
        index += 1
    return _select_candidates(candidates, levels, session_mode, "row")


def _semantic_session(text: str, marker_position: int, level: str) -> str:
    positions = {
        name: text.upper().rfind(marker, 0, marker_position)
        for name, marker in _SESSION_MARKERS.items()
    }
    session, position = max(positions.items(), key=lambda item: item[1])
    if position < 0:
        raise ParserError(f"Semantic {level} marker has no session section")
    return session


def _semantic_fallback(
    soup: BeautifulSoup, levels: tuple[str, ...], session_mode: str
) -> tuple[ParsedSeat, ...]:
    text = " ".join(soup.stripped_strings)
    level_matches = list(_LEVEL_RE.finditer(text))
    candidates: dict[str, list[ParsedSeat]] = {level: [] for level in levels}
    requested = set(levels)
    for index, marker in enumerate(level_matches):
        level = marker.group(1).upper()
        if level not in requested:
            continue
        session = _semantic_session(text, marker.start(), level)
        next_marker = (
            level_matches[index + 1].start()
            if index + 1 < len(level_matches)
            else min(len(text), marker.start() + 500)
        )
        segment = text[marker.start() : next_marker]
        applied_match = _APPLIED_RE.search(segment)
        remaining_match = _REMAINING_RE.search(segment)
        if not applied_match or not remaining_match:
            raise ParserError(f"Semantic {level} counters are incomplete or malformed")
        total = _number(marker.group(2), level, "total")
        applied = _number(applied_match.group(1), level, "applied")
        remaining = _number(remaining_match.group(1), level, "remaining")
        _validate_counters(level, total, applied, remaining)
        candidates[level].append(
            ParsedSeat(session, level, total, applied, remaining, True)
        )
    return _select_candidates(candidates, levels, session_mode, "semantic marker")


def parse_levels(
    html: str,
    levels: tuple[str, ...] | list[str],
    session_mode: str = "Auto",
) -> tuple[ParsedSeat, ...]:
    """Parse requested levels using Auto, one session, or both sessions."""

    requested = _normalize_levels(levels)
    mode = _normalize_session_mode(session_mode)
    if not html.strip():
        raise ParserError("Website returned empty HTML")
    soup = BeautifulSoup(html, "html.parser")
    try:
        return _from_cells(soup, requested, mode)
    except ParserError as primary_error:
        try:
            return _semantic_fallback(soup, requested, mode)
        except ParserError as fallback_error:
            message = (
                f"Primary parser failed ({primary_error}); "
                f"fallback failed ({fallback_error})"
            )
            raise ParserError(message) from fallback_error


def parse_n4(html: str) -> ParsedSeat:
    """Parse Afternoon N4 counters through the legacy singular API."""

    return parse_levels(html, ("N4",), "Afternoon")[0]
