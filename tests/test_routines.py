"""Tests for routines.py — Routine dataclass and CRUD."""

from ollim_bot.scheduling.routines import (
    Routine,
    append_routine,
    list_routines,
    remove_routine,
)


def test_routine_new_generates_id():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert len(routine.id) == 8
    assert routine.message == "test"
    assert routine.cron == "0 9 * * *"
    assert routine.background is False
    assert routine.skip_if_busy is True


def test_routine_new_with_background():
    routine = Routine.new(
        message="bg task", cron="*/5 * * * *", background=True, skip_if_busy=False
    )

    assert routine.background is True
    assert routine.skip_if_busy is False


def test_append_and_list_routines(data_dir):
    r1 = Routine.new(message="morning", cron="0 8 * * *")
    r2 = Routine.new(message="evening", cron="0 18 * * *")

    append_routine(r1)
    append_routine(r2)
    result = list_routines()

    assert len(result) == 2
    messages = {r.message for r in result}
    assert messages == {"morning", "evening"}


def test_list_routines_empty(data_dir):
    assert list_routines() == []


def test_remove_routine(data_dir):
    r = Routine.new(message="test", cron="0 9 * * *")
    append_routine(r)

    removed = remove_routine(r.id)

    assert removed is True
    assert list_routines() == []


def test_remove_routine_not_found(data_dir):
    assert remove_routine("nonexistent") is False


def test_routine_new_defaults_model_isolated():
    routine = Routine.new(message="test", cron="0 9 * * *")

    assert routine.model is None
    assert routine.isolated is False


def test_routine_new_with_model_isolated():
    routine = Routine.new(
        message="check", cron="0 9 * * *", model="haiku", isolated=True
    )

    assert routine.model == "haiku"
    assert routine.isolated is True


def test_routine_model_isolated_roundtrip(data_dir):
    routine = Routine.new(
        message="check",
        cron="0 9 * * *",
        model="sonnet",
        isolated=True,
        background=True,
    )
    append_routine(routine)

    loaded = list_routines()[0]

    assert loaded.model == "sonnet"
    assert loaded.isolated is True
