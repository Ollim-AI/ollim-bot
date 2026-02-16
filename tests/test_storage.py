"""Tests for storage.py — shared JSONL I/O."""

import json
from dataclasses import dataclass

from ollim_bot.storage import append_jsonl, read_jsonl, remove_jsonl


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    name: str
    count: int = 0


def test_read_jsonl_missing_file(tmp_path):
    result = read_jsonl(tmp_path / "nope.jsonl", Item)

    assert result == []


def test_read_jsonl_empty_file(tmp_path):
    (tmp_path / "empty.jsonl").write_text("")

    result = read_jsonl(tmp_path / "empty.jsonl", Item)

    assert result == []


def test_read_jsonl_filters_extra_fields(tmp_path):
    filepath = tmp_path / "items.jsonl"
    filepath.write_text(
        json.dumps({"id": "a", "name": "x", "count": 1, "extra": "ignored"}) + "\n"
    )

    result = read_jsonl(filepath, Item)

    assert len(result) == 1
    assert result[0] == Item(id="a", name="x", count=1)


def test_read_jsonl_skips_blank_lines(tmp_path):
    filepath = tmp_path / "items.jsonl"
    filepath.write_text(
        json.dumps({"id": "a", "name": "x"})
        + "\n"
        + "\n"
        + json.dumps({"id": "b", "name": "y"})
        + "\n"
    )

    result = read_jsonl(filepath, Item)

    assert len(result) == 2


def test_append_jsonl_creates_file(tmp_path):
    filepath = tmp_path / "sub" / "items.jsonl"
    item = Item(id="a", name="hello", count=5)

    append_jsonl(filepath, item, "test commit")

    lines = filepath.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"id": "a", "name": "hello", "count": 5}


def test_append_jsonl_appends_to_existing(tmp_path):
    filepath = tmp_path / "items.jsonl"
    filepath.write_text(json.dumps({"id": "a", "name": "x", "count": 0}) + "\n")

    append_jsonl(filepath, Item(id="b", name="y", count=1), "test")

    lines = filepath.read_text().strip().splitlines()
    assert len(lines) == 2


def test_remove_jsonl_removes_by_id(tmp_path):
    filepath = tmp_path / "items.jsonl"
    filepath.write_text(
        json.dumps({"id": "a", "name": "x", "count": 0})
        + "\n"
        + json.dumps({"id": "b", "name": "y", "count": 1})
        + "\n"
    )

    removed = remove_jsonl(filepath, "a", Item, "test")

    assert removed is True
    result = read_jsonl(filepath, Item)
    assert len(result) == 1
    assert result[0].id == "b"


def test_remove_jsonl_returns_false_if_missing(tmp_path):
    filepath = tmp_path / "items.jsonl"
    filepath.write_text(json.dumps({"id": "a", "name": "x", "count": 0}) + "\n")

    removed = remove_jsonl(filepath, "nope", Item, "test")

    assert removed is False
    assert len(read_jsonl(filepath, Item)) == 1
