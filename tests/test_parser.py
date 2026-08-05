from pathlib import Path

import pytest

from jlpt_seat_watcher.parser import ParserError, parse_n4


def test_parses_current_site_fixture() -> None:
    html = Path("tests/fixtures/current.html").read_text(encoding="utf-8")
    result = parse_n4(html)
    assert (result.session, result.level) == ("Afternoon", "N4")
    assert (result.total, result.applied, result.remaining) == (850, 850, 0)
    assert result.structure_changed is False


def test_semantic_fallback_detects_structure_change() -> None:
    html = """
    <section>FORENOON EXAM APPLICATIONS
    N1 Total: 200 Applied: 20 Remaining: 180</section>
    <section>AFTERNOON EXAM APPLICATIONS
    N4 Total: 1,000 Applied: 990 Remaining: 10</section>
    """
    result = parse_n4(html)
    assert result.remaining == 10
    assert result.structure_changed is True


@pytest.mark.parametrize(
    "html, message",
    [
        ("", "empty HTML"),
        (
            "AFTERNOON EXAM APPLICATIONS N4 Total: 10 Applied: 9 Remaining: 2",
            "do not satisfy",
        ),
        (
            "AFTERNOON EXAM APPLICATIONS N4 Total: 10 Applied: x Remaining: 10",
            "incomplete or malformed",
        ),
        (
            "AFTERNOON EXAM APPLICATIONS N4 Total: 10 Applied: 10 Remaining: 0 "
            "N4 Total: 20 Applied: 20 Remaining: 0",
            "exactly one semantic N4 marker",
        ),
        (
            "FORENOON EXAM APPLICATIONS N4 Total: 10 Applied: 10 Remaining: 0",
            "not in the Afternoon",
        ),
    ],
)
def test_rejects_unsafe_content(html: str, message: str) -> None:
    with pytest.raises(ParserError, match=message):
        parse_n4(html)
