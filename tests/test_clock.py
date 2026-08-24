from datetime import datetime, timezone

import pytest

from core.clock import FixedClock


def test_fixed_clock_now_returns_the_given_datetime():
    dt = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(dt)
    assert clock.now() == dt


def test_fixed_clock_rejects_naive_datetime():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 8, 24, 0, 0))  # no tzinfo


def test_fixed_clock_advance_adds_hours():
    dt = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(dt)
    advanced = clock.advance(48)
    assert advanced.now() == datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc)


def test_fixed_clock_advance_does_not_mutate_the_original():
    dt = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(dt)
    clock.advance(48)
    assert clock.now() == dt


def test_fixed_clock_advance_returns_a_new_instance():
    dt = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(dt)
    advanced = clock.advance(1)
    assert advanced is not clock
