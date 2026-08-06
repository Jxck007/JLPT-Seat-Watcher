from pathlib import Path

import pytest

from jlpt_seat_watcher.parser import ParserError, parse_levels, parse_n4


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


def test_parses_all_levels_in_requested_order() -> None:
    html = Path("tests/fixtures/current.html").read_text(encoding="utf-8")
    results = parse_levels(html, ["N5", "N4", "N3", "N2", "N1"])
    assert [result.level for result in results] == ["N5", "N4", "N3", "N2", "N1"]
    assert [result.session for result in results] == [
        "Afternoon",
        "Afternoon",
        "Afternoon",
        "Forenoon",
        "Forenoon",
    ]
    assert [result.remaining for result in results] == [671, 0, 512, 439, 187]


def test_semantic_fallback_parses_multiple_levels() -> None:
    html = """
    <section>FORENOON EXAM APPLICATIONS
    N1 Total: 200 Applied: 20 Remaining: 180
    N2 Total: 500 Applied: 60 Remaining: 440</section>
    <section>AFTERNOON EXAM APPLICATIONS
    N3 Total: 800 Applied: 300 Remaining: 500
    N4 Total: 850 Applied: 849 Remaining: 1
    N5 Total: 1000 Applied: 900 Remaining: 100</section>
    """
    results = parse_levels(html, ["N1", "N4", "N5"])
    assert [(item.level, item.remaining) for item in results] == [
        ("N1", 180),
        ("N4", 1),
        ("N5", 100),
    ]
    assert all(item.structure_changed for item in results)


def test_rejects_invalid_level_requests() -> None:
    html = Path("tests/fixtures/current.html").read_text(encoding="utf-8")
    with pytest.raises(ParserError, match="supported"):
        parse_levels(html, ["N6"])
    with pytest.raises(ParserError, match="duplicates"):
        parse_levels(html, ["N4", "N4"])


def test_auto_detects_selected_level_without_fixed_session() -> None:
    html = """
    <div class="table-container1">
      <div class="cell1">FORENOON EXAM APPLICATIONS</div>
      <div class="cell1">N4 Total: 100</div>
      <div class="cell1">Applied: 99</div>
      <div class="cell1">Remaining: 1</div>
    </div>
    """
    result = parse_levels(html, ["N4"], "Auto")[0]
    assert (result.level, result.session, result.remaining) == ("N4", "Forenoon", 1)


def test_explicit_session_filters_selected_level() -> None:
    html = Path("tests/fixtures/current.html").read_text(encoding="utf-8")
    assert parse_levels(html, ["N2"], "Forenoon")[0].session == "Forenoon"
    assert parse_levels(html, ["N4"], "Afternoon")[0].session == "Afternoon"
    with pytest.raises(ParserError, match="not in the Afternoon"):
        parse_levels(html, ["N2"], "Afternoon")


def test_both_returns_same_level_from_both_sessions() -> None:
    html = """
    <div class="table-container1">
      <div class="cell1">FORENOON EXAM APPLICATIONS</div>
      <div class="cell1">N4 Total: 100</div>
      <div class="cell1">Applied: 99</div>
      <div class="cell1">Remaining: 1</div>
      <div class="cell1">AFTERNOON EXAM APPLICATIONS</div>
      <div class="cell1">N4 Total: 200</div>
      <div class="cell1">Applied: 198</div>
      <div class="cell1">Remaining: 2</div>
    </div>
    """
    results = parse_levels(html, ["N4"], "Both")
    assert [(item.session, item.remaining) for item in results] == [
        ("Forenoon", 1),
        ("Afternoon", 2),
    ]
    with pytest.raises(ParserError, match="Auto mode"):
        parse_levels(html, ["N4"], "Auto")
    afternoon = parse_levels(html, ["N4"], "Afternoon")
    assert [(item.session, item.remaining) for item in afternoon] == [("Afternoon", 2)]


def test_semantic_both_returns_each_session() -> None:
    html = """
    <section>FORENOON EXAM APPLICATIONS
    N3 Total: 100 Applied: 90 Remaining: 10</section>
    <section>AFTERNOON EXAM APPLICATIONS
    N3 Total: 200 Applied: 180 Remaining: 20</section>
    """
    results = parse_levels(html, ["N3"], "Both")
    assert [(item.session, item.remaining) for item in results] == [
        ("Forenoon", 10),
        ("Afternoon", 20),
    ]
    assert all(item.structure_changed for item in results)


def test_rejects_invalid_session_mode() -> None:
    html = Path("tests/fixtures/current.html").read_text(encoding="utf-8")
    with pytest.raises(ParserError, match="session mode"):
        parse_levels(html, ["N4"], "Evening")


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
