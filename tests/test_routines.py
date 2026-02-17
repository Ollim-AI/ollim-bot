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
    assert result[0].message == "morning"
    assert result[1].message == "evening"


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
