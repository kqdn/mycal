"""Solver settings, shared by solve() and the engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Engine = Literal["backtracking", "cp_sat"]


@dataclass(frozen=True, slots=True)
class SolverSettings:
    """Tunable solver settings.

    `timezone` is my home IANA timezone. The solver works in UTC and uses it
    only to tell which local day a block falls on (for one_block_per_day). It
    has no default on purpose: a silent UTC default would split days at the
    wrong hour. `slot_min` is the one place the slot size lives.
    `time_limit_s` caps the CP-SAT search.
    """

    timezone: str
    slot_min: int = 15
    engine: Engine = "backtracking"
    time_limit_s: float = 10.0

    def __post_init__(self) -> None:
        if self.slot_min <= 0:
            raise ValueError("slot_min must be positive")
        if self.time_limit_s <= 0:
            raise ValueError("time_limit_s must be positive")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Unknown timezone {self.timezone!r}") from error
