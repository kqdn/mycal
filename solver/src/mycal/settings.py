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
    `earliness_slack_min` is how much later than optimal, per flexible block,
    the lowest score tier (earlier in the frame) may come out. CP-SAT stops
    once it proves its plan is that close; every higher tier stays exact.
    `work_limit` caps the CP-SAT search in deterministic time (CP-SAT's
    max_deterministic_time, about a second of work on a typical laptop, but
    counted the same on every machine), so the same input always gives the
    same plan. There is no wall-clock limit on purpose.
    """

    timezone: str
    slot_min: int = 15
    engine: Engine = "cp_sat"
    earliness_slack_min: int = 15
    work_limit: float = 20.0

    def __post_init__(self) -> None:
        if self.slot_min <= 0:
            raise ValueError("slot_min must be positive")
        if self.earliness_slack_min < 0:
            raise ValueError("earliness_slack_min must not be negative")
        if self.work_limit <= 0:
            raise ValueError("work_limit must be positive")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Unknown timezone {self.timezone!r}") from error
