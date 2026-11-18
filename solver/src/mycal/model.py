"""Core entities from the PRD: Item, Block, WorkFrame, Constraint and Series.

Exact moments in time are timezone-aware UTC datetimes. Repeating times of
day (WorkFrame start/end, series templates) are local wall-clock times plus an
IANA timezone name, because a fixed UTC time of day would drift by an hour
across DST.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any, Literal
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
    makes up for. `one_block_per_day` makes "no two blocks on the same local
    day" a hard constraint; when off, spreading out is only a soft penalty.
    `series_id` and `occurrence_date` are set together, only on occurrences of
    a Series.
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
    one_block_per_day: bool = False
    on_miss: OnMiss = OnMiss.RESCHEDULE
    catch_up_of: UUID | None = None
    series_id: UUID | None = None
    occurrence_date: date | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_utc(self.deadline, "Item.deadline")
        if (self.series_id is None) != (self.occurrence_date is None):
            raise ValueError("Item.series_id and Item.occurrence_date must be set together")


MISSABLE = (BlockStatus.PARTIAL, BlockStatus.MISSED, BlockStatus.UNANSWERED)


@dataclass(slots=True)
class Block:
    """One calendar slot for an item. `locked` means placed by hand: the solver keeps it.

    `missed_action` is the on-miss policy that ran on the block's missed part
    (all of a missed or unanswered block, the rest of a partial one). None
    means none ran yet: an Ask still waiting for an answer. It is never ASK,
    and only blocks with a missed part have one.
    """

    item_id: UUID
    start: datetime
    end: datetime
    locked: bool = False
    status: BlockStatus = BlockStatus.PLANNED
    completed_at: datetime | None = None
    actual_min: int | None = None
    missed_action: OnMiss | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_utc(self.start, "Block.start")
        _require_utc(self.end, "Block.end")
        _require_utc(self.completed_at, "Block.completed_at")
        if self.start >= self.end:
            raise ValueError("Block.start must be before Block.end")
        if self.missed_action is OnMiss.ASK:
            raise ValueError("Block.missed_action is the policy that ran, never ASK")
        if self.missed_action is not None and self.status not in MISSABLE:
            raise ValueError(f"A {self.status.value} block has no missed part, so no missed_action")


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


@dataclass(slots=True)
class Rule:
    """A repeat rule: a subset of iCalendar RRULE.

    `freq` is "daily" or "weekly"; `interval` means every N days or weeks.
    `weekdays` (0 = Monday) is required for weekly and must be empty for daily.
    """

    freq: Literal["daily", "weekly"]
    interval: int = 1
    weekdays: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.freq not in ("daily", "weekly"):
            raise ValueError(f"Rule.freq must be 'daily' or 'weekly', got {self.freq!r}")
        if self.interval < 1:
            raise ValueError("Rule.interval must be at least 1")
        if self.freq == "weekly" and not self.weekdays:
            raise ValueError("A weekly rule needs weekdays")
        if self.freq == "daily" and self.weekdays:
            raise ValueError("A daily rule takes no weekdays")
        if any(day not in range(7) for day in self.weekdays):
            raise ValueError("Rule weekdays must be in 0..6")


# Template params per preset. Templates hold times of day only, never dates:
# the occurrence date fills in the day.
TEMPLATE_PARAMS: dict[FlexPreset, tuple[set[str], set[str]]] = {
    # preset: (required keys, optional keys)
    FlexPreset.EXACT: ({"start_time", "end_time"}, set()),
    FlexPreset.DAY: (set(), set()),
    FlexPreset.DAY_RANGE: ({"start_time", "end_time"}, set()),
    FlexPreset.DAYS: ({"weekdays"}, {"start_time", "end_time", "every_day", "session_min"}),
    FlexPreset.BEFORE_DEADLINE: (set(), set()),
}


@dataclass(slots=True)
class ItemTemplate:
    """The item fields a Series copies onto each occurrence.

    `deadline_time` is a local time of day on the occurrence date. Custom is
    not allowed: its painted windows are fixed dates.
    """

    flex_preset: FlexPreset
    preset_params: dict[str, Any] = field(default_factory=dict)
    estimate_min: int | None = None
    deadline_time: time | None = None
    checkable: bool = False
    on_miss: OnMiss = OnMiss.RESCHEDULE
    max_chunk_min: int | None = None
    one_block_per_day: bool = False

    def __post_init__(self) -> None:
        if self.flex_preset not in TEMPLATE_PARAMS:
            raise ValueError(f"Preset {self.flex_preset.value!r} cannot be used in a series template")
        required, optional = TEMPLATE_PARAMS[self.flex_preset]
        keys = set(self.preset_params)
        if missing := required - keys:
            raise ValueError(f"Template is missing {sorted(missing)}")
        if unknown := keys - required - optional:
            raise ValueError(f"Template has unknown keys {sorted(unknown)}")
        if any(isinstance(value, date) for value in self.preset_params.values()):
            raise ValueError("Templates hold times of day only, not dates")
        if self.flex_preset is FlexPreset.BEFORE_DEADLINE and self.deadline_time is None:
            raise ValueError("A before_deadline template needs deadline_time")


@dataclass(slots=True)
class Series:
    """A repeat rule plus an item template. Each occurrence becomes a normal Item.

    Dates are local to `timezone`. `end_date` is optional and inclusive.
    `skipped_dates` never get an occurrence.
    """

    title: str
    rule: Rule
    timezone: str
    start_date: date
    template: ItemTemplate
    end_date: date | None = None
    skipped_dates: list[date] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Series.end_date must not be before start_date")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Unknown timezone {self.timezone!r}") from error
