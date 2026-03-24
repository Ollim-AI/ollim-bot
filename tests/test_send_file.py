"""Tests for send_file MCP tool."""

import asyncio
from pathlib import Path

from ollim_bot.agent_tools import send_file
from ollim_bot.channel import init_channel
from ollim_bot.fork_state import (
    BgForkConfig,
    set_bg_fork_config,
    set_busy,
    set_in_fork,
)

_send = send_file.handler


class _FakeMessage:
    _next_id = 1

    def __init__(self):
        self.id = _FakeMessage._next_id
        _FakeMessage._next_id += 1


class InMemoryChannel:
    def __init__(self):
        self.messages: list[dict] = []

    async def send(self, content=None, *, embed=None, view=None, file=None):
        self.messages.append({"content": content, "file": file})
        return _FakeMessage()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _text(result: dict) -> str:
    return result["content"][0]["text"]


def test_send_file_success(tmp_path: Path):
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    ch = InMemoryChannel()
    init_channel(ch)

    result = _run(_send({"file_path": str(f)}))

    assert "File sent: hello.txt" in _text(result)
    assert len(ch.messages) == 1
    sent = ch.messages[0]
    assert sent["file"] is not None
    assert sent["file"].filename == "hello.txt"


def test_send_file_with_message(tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-fake")
    ch = InMemoryChannel()
    init_channel(ch)

    result = _run(_send({"file_path": str(f), "message": "Here's your doc"}))

    assert "File sent" in _text(result)
    assert ch.messages[0]["content"] == "Here's your doc"


def test_send_file_not_found():
    ch = InMemoryChannel()
    init_channel(ch)

    result = _run(_send({"file_path": "/nonexistent/path/file.txt"}))

    assert "Error: file not found or not a regular file" in _text(result)
    assert len(ch.messages) == 0


def test_send_file_directory(tmp_path: Path):
    ch = InMemoryChannel()
    init_channel(ch)

    result = _run(_send({"file_path": str(tmp_path)}))

    assert "Error: file not found or not a regular file" in _text(result)
    assert len(ch.messages) == 0


def test_send_file_too_large(tmp_path: Path, monkeypatch):
    f = tmp_path / "big.bin"
    f.write_bytes(b"x")  # small file, we patch stat

    import ollim_bot.agent_tools as mod

    monkeypatch.setattr(mod, "_MAX_FILE_SIZE", 10)  # 10 bytes limit

    ch = InMemoryChannel()
    init_channel(ch)

    # Write more than 10 bytes
    f.write_bytes(b"x" * 20)
    result = _run(_send({"file_path": str(f)}))

    assert "Error:" in _text(result)
    assert "exceeds" in _text(result)
    assert len(ch.messages) == 0


def test_send_file_bg_budget(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("note")
    ch = InMemoryChannel()
    init_channel(ch)

    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=True))
    set_busy(True)
    try:
        result = _run(_send({"file_path": str(f)}))
        assert "mid-conversation" in _text(result)
        assert len(ch.messages) == 0
    finally:
        set_in_fork(False)
        set_bg_fork_config(BgForkConfig())
        set_busy(False)


def test_send_file_bg_ping_disabled(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("note")
    ch = InMemoryChannel()
    init_channel(ch)

    set_in_fork(True)
    set_bg_fork_config(BgForkConfig(allow_ping=False))
    try:
        result = _run(_send({"file_path": str(f)}))
        assert "disabled" in _text(result)
        assert len(ch.messages) == 0
    finally:
        set_in_fork(False)
        set_bg_fork_config(BgForkConfig())


def test_send_file_no_channel():
    init_channel(None)

    result = _run(_send({"file_path": "/tmp/any.txt"}))

    assert "Error: no active channel" in _text(result)


def test_send_file_tilde_expansion(tmp_path: Path, monkeypatch):
    """Tilde in path is expanded correctly."""
    f = tmp_path / "resume.pdf"
    f.write_bytes(b"%PDF-fake")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows uses USERPROFILE
    ch = InMemoryChannel()
    init_channel(ch)

    result = _run(_send({"file_path": "~/resume.pdf"}))

    assert "File sent: resume.pdf" in _text(result)
    assert len(ch.messages) == 1
