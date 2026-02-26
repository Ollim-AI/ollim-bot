"""Tests for inquiries.py — button prompt persistence."""

import json
import time

from ollim_bot import inquiries


def test_register_and_pop(data_dir):
    uid = inquiries.register("What should I focus on?")

    assert len(uid) == 8

    prompt = inquiries.pop(uid)

    assert prompt == "What should I focus on?"


def test_pop_missing_returns_none(data_dir):
    assert inquiries.pop("nonexistent") is None


def test_pop_removes_entry(data_dir):
    uid = inquiries.register("test prompt")

    inquiries.pop(uid)

    assert inquiries.pop(uid) is None


def test_expired_entries_filtered(data_dir, monkeypatch):
    inquiries_file = data_dir / "inquiries.json"
    old_ts = time.time() - (8 * 24 * 3600)  # 8 days ago
    inquiries_file.write_text(json.dumps({"old_id": {"prompt": "expired", "ts": old_ts}}))

    assert inquiries.pop("old_id") is None


def test_register_multiple(data_dir):
    uid1 = inquiries.register("first")
    uid2 = inquiries.register("second")

    assert uid1 != uid2
    assert inquiries.pop(uid1) == "first"
    assert inquiries.pop(uid2) == "second"
