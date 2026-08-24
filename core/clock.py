"""Injected clock. core/ never reads the wall clock — see tests/test_boundary.py.

Every function in core/ that needs "now" takes a Clock (or a datetime) as a
parameter. Time only moves when the caller asks for it (FixedClock.advance),
which is what makes a (seed, clock) pair replayable byte-for-byte.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return a tz-aware UTC datetime. Never the real wall clock."""
        ...


@dataclass(frozen=True)
class FixedClock:
    """A clock pinned to one instant. .advance() returns a NEW FixedClock —
    this class never mutates in place, so a held reference stays a fixed point
    in time even after the caller advances."""

    dt: datetime

    def __post_init__(self) -> None:
        if self.dt.tzinfo is None:
            raise ValueError("FixedClock requires a tz-aware datetime (got a naive one)")

    def now(self) -> datetime:
        return self.dt

    def advance(self, hours: float) -> "FixedClock":
        return FixedClock(self.dt + timedelta(hours=hours))
