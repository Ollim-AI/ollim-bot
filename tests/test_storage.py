"""Tests for storage.py — shared JSONL and markdown I/O."""

import json
from dataclasses import dataclass

from ollim_bot.storage import (
    _slugify,
    append_jsonl,
    read_jsonl,
    read_md_dir,
    remove_jsonl,
    remove_md,
    write_md,
)


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    name: str
    count: int = 0


@dataclass(frozen=True, slots=True)
class MdItem:
    id: str
    message: str
    tag: str = ""


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


# --- Markdown storage tests ---


def test_slugify_basic():
    assert _slugify("Hello World") == "hello-world"


def test_slugify_strips_non_alphanum():
    assert _slugify("Check email & summarize!") == "check-email-summarize"


def test_slugify_collapses_runs():
    assert _slugify("a---b   c") == "a-b-c"


def test_slugify_truncates():
    long = "a" * 100
    result = _slugify(long, max_len=50)

    assert len(result) <= 50


def test_slugify_strips_edges():
    assert _slugify("  --hello--  ") == "hello"


def test_read_md_dir_missing_dir(tmp_path):
    result = read_md_dir(tmp_path / "nonexistent", MdItem)

    assert result == []


def test_read_md_dir_empty_dir(tmp_path):
    d = tmp_path / "items"
    d.mkdir()

    result = read_md_dir(d, MdItem)

    assert result == []


def test_read_md_dir_filters_extra_fields(tmp_path):
    d = tmp_path / "items"
    d.mkdir()
    (d / "test.md").write_text('---\nid: "a"\ntag: "x"\nextra: "ignored"\n---\nhello\n')

    result = read_md_dir(d, MdItem)

    assert len(result) == 1
    assert result[0] == MdItem(id="a", message="hello", tag="x")


def test_read_md_dir_skips_corrupt_files(tmp_path):
    d = tmp_path / "items"
    d.mkdir()
    (d / "good.md").write_text('---\nid: "a"\n---\ngood message\n')
    (d / "bad.md").write_text("not yaml at all {{{")

    result = read_md_dir(d, MdItem)

    assert len(result) == 1
    assert result[0].id == "a"


def test_write_md_creates_dir_and_file(tmp_path):
    d = tmp_path / "items"
    item = MdItem(id="abc", message="Check the deployment")

    write_md(d, item, "test")

    files = list(d.glob("*.md"))
    assert len(files) == 1
    assert "check-the-deployment" in files[0].name


def test_write_md_slug_collision(tmp_path):
    d = tmp_path / "items"
    item1 = MdItem(id="aaa", message="same message")
    item2 = MdItem(id="bbb", message="same message")

    write_md(d, item1, "test")
    write_md(d, item2, "test")

    files = {f.name for f in d.glob("*.md")}

    assert len(files) == 2
    assert "same-message.md" in files
    assert "same-message-2.md" in files


def test_write_md_roundtrip(tmp_path):
    d = tmp_path / "items"
    item = MdItem(id="abc", message="hello world", tag="important")

    write_md(d, item, "test")
    result = read_md_dir(d, MdItem)

    assert len(result) == 1
    assert result[0] == item


def test_write_md_omits_default_fields(tmp_path):
    d = tmp_path / "items"
    item = MdItem(id="abc", message="test", tag="")  # tag="" is the default

    write_md(d, item, "test")

    content = next(d.glob("*.md")).read_text()
    assert "tag" not in content.split("---")[1]  # not in YAML frontmatter


def test_multiline_body_preserved(tmp_path):
    d = tmp_path / "items"
    body = "First paragraph.\n\nSecond paragraph.\n\n- bullet one\n- bullet two"
    item = MdItem(id="abc", message=body)

    write_md(d, item, "test")
    result = read_md_dir(d, MdItem)

    assert result[0].message == body


def test_remove_md_deletes_file(tmp_path):
    d = tmp_path / "items"
    d.mkdir()
    (d / "hello.md").write_text('---\nid: "abc"\n---\nhello\n')

    removed = remove_md(d, "abc", "test")

    assert removed is True
    assert list(d.glob("*.md")) == []


def test_remove_md_returns_false_if_missing(tmp_path):
    d = tmp_path / "items"
    d.mkdir()

    removed = remove_md(d, "nonexistent", "test")

    assert removed is False
