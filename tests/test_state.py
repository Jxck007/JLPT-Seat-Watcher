from __future__ import annotations

import json
from pathlib import Path

import pytest

from jlpt_seat_watcher.state import StateError, StateStore, new_state


def test_missing_state_and_atomic_save(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "data" / "state.json")
    state = store.load()
    assert state["schema_version"] == 1
    state["statistics"]["checks_total"] = 4
    store.save(state)
    assert store.load()["statistics"]["checks_total"] == 4
    assert not list(store.path.parent.glob("*.tmp"))


def test_transaction_persists(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    with store.transaction() as state:
        state["statistics"]["successes"] = 2
    assert store.load()["statistics"]["successes"] == 2


def test_corrupt_state_is_preserved_and_recovered(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not-json", encoding="utf-8")
    store = StateStore(path)
    assert store.load()["schema_version"] == 1
    preserved = list(tmp_path.glob("state.corrupt-*.json"))
    assert len(preserved) == 1
    assert preserved[0].read_text(encoding="utf-8") == "not-json"


def test_unrecoverable_load_raises(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(StateError, match="unreadable"):
        StateStore(path).load(recover=False)


def test_new_state_instances_are_independent() -> None:
    first = new_state()
    second = new_state()
    first["statistics"]["checks_total"] = 9
    assert second["statistics"]["checks_total"] == 0
