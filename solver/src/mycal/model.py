"""Core entities from the PRD: Item, Block, WorkFrame and Constraint.

Exact moments in time are timezone-aware UTC datetimes. Repeating times of
day (WorkFrame start/end) are local wall-clock times plus an IANA timezone
name, because a fixed UTC time of day would drift by an hour across DST.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class FlexPreset(Enum):
    """How an item may move. Each preset compiles to Item.windows."""

    EXACT = "exact"
    DAY = "day"
    DAY_RANGE = "day_range"
    DAYS = "days"
    BEFORE_DEADLINE = "before_deadline"
    CUSTOM = "custom"


class OnMiss(Enum):
    """What a missed (or partly missed) block triggers."""

    RESCHEDULE = "reschedule"
    CATCH_UP = "catch_up"
    SKIP = "skip"
    ASK = "ask"


class BlockStatus(Enum):
    PLANNED = "planned"
    DONE = "done"
    PARTIAL = "partial"
    MISSED = "missed"
    UNANSWERED = "unanswered"


def _require_utc(value: datetime | None, name: str) -> None:
    """Raise ValueError unless value is None or a UTC-aware datetime."""
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime, got {value!r}")


@dataclass(frozen=True, slots=True)
class Window:
    """A half-open interval [start, end) in UTC where a block may be placed."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_utc(self.start, "Window.start")
        _require_utc(self.end, "Window.end")
        if self.start >= self.end:
            raise ValueError("Window.start must be before Window.end")


@dataclass(slots=True)
class Item:
    """The thing to do. Its calendar appearances are Blocks.

    The solver reads only `windows`; `flex_preset` and `preset_params` exist so
    the UI can show and edit the preset that produced them. Subtasks are items
    with a `parent_id`. `catch_up_of` is the id of the missed Block this item
    makes up for.
    """

    title: str
    flex_preset: FlexPreset
    windows: list[Window] = field(default_factory=list)
    preset_params: dict[str, Any] = field(default_factory=dict)
    checkable: bool = False
    estimate_min: int | None = None
    deadline: datetime | None = None
    parent_id: UUID | None = None
    depends_on: list[UUID] = field(default_factory=list)
    max_chunk_min: int | None = None
    on_miss: OnMiss = OnMiss.RESCHEDULE
    catch_up_of: UUID | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_utc(self.deadline, "Item.deadline")


@dataclass(slots=True)
class Block:
    """One calendar slot for an item. `locked` means placed by hand: the solver keeps it."""

    item_id: UUID
    start: datetime
    end: datetime
    locked: bool = False
    status: BlockStatus = BlockStatus.PLANNED
    completed_at: datetime | None = None
    actual_min: int | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_utc(self.start, "Block.start")
        _require_utc(self.end, "Block.end")
        _require_utc(self.completed_at, "Block.completed_at")
        if self.start >= self.end:
            raise ValueError("Block.start must be before Block.end")


@dataclass(slots=True)
class WorkFrame:
    """A repeating window where flexible blocks may live, e.g. weekdays 9am to 6pm.

    `start_time` and `end_time` are naive local times in `timezone` (an IANA
    name such as "America/Los_Angeles"). If `end_time` is earlier than
    `start_time`, the frame crosses midnight and ends the next day.
    `weekdays` uses 0 = Monday, matching `datetime.weekday()`, and names the
    day each frame starts on.
    """

    name: str
    weekdays: list[int]
    start_time: time
    end_time: time
    timezone: str
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.start_time.tzinfo is not None or self.end_time.tzinfo is not None:
            raise ValueError("WorkFrame times must be naive local times")
        if self.start_time == self.end_time:
            raise ValueError("WorkFrame start_time and end_time must differ")
        if any(day not in range(7) for day in self.weekdays):
            raise ValueError("WorkFrame weekdays must be in 0..6")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Unknown timezone {self.timezone!r}") from error


@dataclass(slots=True)
class Constraint:
    """An extra rule. New kinds need no schema change; `params` holds the details."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    hard: bool = False
    id: UUID = field(default_factory=uuid4)
