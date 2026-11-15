"""Turn solve() inputs into a slot-based problem that every engine searches.

Time is a grid of slots of `slot_min` minutes, numbered from the Unix epoch
in UTC. Each Chunk is one block still to be placed; its candidates are the
start slots where it fits entirely inside one of its item's windows and ends
by the item's deadline.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from mycal.model import Block, BlockStatus, Constraint, Item, Window, WorkFrame
from mycal.settings import SolverSettings

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One piece of an item's remaining work, to become one block."""

    item_id: UUID
    block_id: UUID
    size: int
    candidates: tuple[int, ...]
    previous_start: int | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    """What an engine returns: new blocks for every chunk (None if none fit) and how the search ended.

    `status` is CP-SAT's status name (OPTIMAL, FEASIBLE when stopped at the time
    limit, INFEASIBLE), or FOUND / INFEASIBLE for backtracking.
    """

    blocks: list[Block] | None
    status: str


@dataclass(frozen=True, slots=True)
class DailyLimit:
    """Hard cap on scheduled minutes on matching local days (a daily_limit Constraint).

    Every block counts toward the local day it starts on: fixed, kept and newly
    placed blocks alike.
    """

    max_min: int
    weekdays: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Target:
    """Which items a soft constraint applies to. Both sets empty means every item.

    A series id matches all of that series' occurrences, so a rule keeps
    applying when next week's occurrence gets a new item id.
    """

    item_ids: frozenset[UUID] = frozenset()
    series_ids: frozenset[UUID] = frozenset()

    def matches(self, item: Item) -> bool:
        if not self.item_ids and not self.series_ids:
            return True
        return item.id in self.item_ids or item.series_id in self.series_ids


@dataclass(frozen=True, slots=True)
class TimePreference:
    """Soft: matching blocks should sit inside `windows` (or outside them, if `avoid`).

    The penalty is the number of a block's slots on the wrong side, times `weight`.
    """

    target: Target
    avoid: bool
    windows: tuple[Window, ...]
    weight: int


@dataclass(frozen=True, slots=True)
class RestBetween:
    """Soft: two sessions of a matching item should be more than `min_gap_days` local days apart.

    Each pair that is too close costs the shorter session's length in slots,
    times `weight`, so a missed rest day weighs about as much as one session at
    a non-preferred time. Kept blocks that count as done work count as sessions.
    """

    target: Target
    min_gap_days: int
    weight: int


@dataclass(slots=True)
class Problem:
    settings: SolverSettings
    items: dict[UUID, Item]
    kept: list[Block]
    chunks: list[Chunk]
    work_frames: list[WorkFrame] = field(default_factory=list)
    daily_limits: list[DailyLimit] = field(default_factory=list)
    preferences: list[TimePreference] = field(default_factory=list)
    rests: list[RestBetween] = field(default_factory=list)


def day_limit_min(limits: list[DailyLimit], day: date) -> int | None:
    """The tightest limit for this local day, or None if no limit applies."""
    caps = [limit.max_min for limit in limits if day.weekday() in limit.weekdays]
    return min(caps) if caps else None


def kept_minutes_by_day(kept: list[Block], timezone: str) -> dict[date, int]:
    """Minutes of kept blocks per local start day."""
    zone = ZoneInfo(timezone)
    minutes: dict[date, int] = defaultdict(int)
    for block in kept:
        minutes[block.start.astimezone(zone).date()] += (block.end - block.start) // timedelta(minutes=1)
    return minutes


def floor_slot(moment: datetime, slot_min: int) -> int:
    return (moment - EPOCH) // timedelta(minutes=slot_min)


def ceil_slot(moment: datetime, slot_min: int) -> int:
    return -((EPOCH - moment) // timedelta(minutes=slot_min))


def slot_start(slot: int, slot_min: int) -> datetime:
    return EPOCH + slot * timedelta(minutes=slot_min)


def is_kept(block: Block) -> bool:
    """Locked blocks and completion history are kept; unlocked planned blocks get re-placed."""
    return block.locked or block.status is not BlockStatus.PLANNED


def covered_min(block: Block) -> int:
    """Minutes of an item's work this kept block already accounts for."""
    length = int((block.end - block.start) / timedelta(minutes=1))
    if block.status in (BlockStatus.DONE, BlockStatus.PARTIAL):
        return block.actual_min if block.actual_min is not None else length
    if block.locked and block.status is BlockStatus.PLANNED:
        return length
    return 0


def build_problem(
    items: list[Item],
    blocks: list[Block],
    constraints: list[Constraint],
    settings: SolverSettings,
    work_frames: list[WorkFrame] = [],
) -> Problem:
    """Work out the kept blocks and the chunks still to place.

    Work frames are passed through only so engines can measure each day's
    capacity; placement still follows item windows alone.

    Raises ValueError for a constraint kind no engine supports yet (unknown
    soft kinds are ignored), so a rule is never silently dropped, for bad
    constraint params, and for an item with no estimate and more than one window.
    """
    daily_limits, preferences, rests = _parse_constraints(constraints, {item.id for item in items})

    kept = [b for b in blocks if is_kept(b)]
    replaced = sorted((b for b in blocks if not is_kept(b)), key=lambda b: b.start)

    chunks: list[Chunk] = []
    for item in items:
        item_kept = [b for b in kept if b.item_id == item.id]
        item_old = [b for b in replaced if b.item_id == item.id]
        chunks.extend(_item_chunks(item, item_kept, item_old, settings.slot_min))

    return Problem(
        settings,
        {item.id: item for item in items},
        kept,
        chunks,
        work_frames=list(work_frames),
        daily_limits=daily_limits,
        preferences=preferences,
        rests=rests,
    )


def _parse_constraints(
    constraints: list[Constraint], item_ids: set[UUID]
) -> tuple[list[DailyLimit], list[TimePreference], list[RestBetween]]:
    limits, preferences, rests = [], [], []
    for constraint in constraints:
        if constraint.kind == "daily_limit":
            if not constraint.hard:
                raise ValueError("Soft daily_limit is not supported yet; set hard = true")
            limits.append(_parse_daily_limit(constraint.params))
        elif constraint.kind == "time_preference":
            preferences.append(_parse_time_preference(constraint, item_ids))
        elif constraint.kind == "rest_between":
            rests.append(_parse_rest_between(constraint, item_ids))
        elif constraint.hard:
            raise ValueError(f"Hard constraint kind {constraint.kind!r} is not supported yet")
    return limits, preferences, rests


def _soft_basics(constraint: Constraint, allowed: set[str], item_ids: set[UUID]) -> tuple[Target, int]:
    """Checks shared by soft kinds; returns the target and the weight in hundredths.

    CP-SAT only takes integer coefficients, so weights are scaled by 100 and rounded.
    """
    kind, params = constraint.kind, constraint.params
    if constraint.hard:
        raise ValueError(f"Hard {kind} is not supported yet; leave hard = false")
    if unknown := set(params) - allowed - {"item_ids", "series_ids"}:
        raise ValueError(f"{kind} has unknown params {sorted(unknown)}")
    targets = {key: params.get(key, []) for key in ("item_ids", "series_ids")}
    for key, ids in targets.items():
        if not isinstance(ids, list) or not all(isinstance(i, UUID) for i in ids):
            raise ValueError(f"{kind} {key} must be a list of UUIDs, got {ids!r}")
    if missing := set(targets["item_ids"]) - item_ids:
        raise ValueError(f"{kind} names unknown item ids {sorted(map(str, missing))}")
    weight = constraint.weight
    if not isinstance(weight, int | float) or isinstance(weight, bool) or weight < 0:
        raise ValueError(f"{kind} weight must be a non-negative number, got {weight!r}")
    target = Target(frozenset(targets["item_ids"]), frozenset(targets["series_ids"]))
    return target, round(weight * 100)


def _parse_time_preference(constraint: Constraint, item_ids: set[UUID]) -> TimePreference:
    """Params: windows (compiled UTC windows), mode ("prefer" or "avoid"), optional targets."""
    params = constraint.params
    if "windows" not in params and {"ranges", "weekdays", "start_time", "end_time"} & set(params):
        raise ValueError("time_preference has local times; turn them into windows with compile_constraint first")
    target, weight = _soft_basics(constraint, {"windows", "mode"}, item_ids)
    mode = params.get("mode", "prefer")
    if mode not in ("prefer", "avoid"):
        raise ValueError(f"time_preference mode must be 'prefer' or 'avoid', got {mode!r}")
    windows = params.get("windows")
    if not isinstance(windows, list) or not all(isinstance(w, Window) for w in windows):
        raise ValueError(f"time_preference windows must be a list of Window, got {windows!r}")
    return TimePreference(target, mode == "avoid", tuple(windows), weight)


def _parse_rest_between(constraint: Constraint, item_ids: set[UUID]) -> RestBetween:
    """Params: min_gap_days (free days wanted between sessions, default 1), optional targets."""
    target, weight = _soft_basics(constraint, {"min_gap_days"}, item_ids)
    gap = constraint.params.get("min_gap_days", 1)
    if not isinstance(gap, int) or isinstance(gap, bool) or gap < 1:
        raise ValueError(f"rest_between min_gap_days must be a positive integer, got {gap!r}")
    return RestBetween(target, gap, weight)


def _parse_daily_limit(params: dict[str, Any]) -> DailyLimit:
    """Params: max_min (minutes, required) and weekdays (0 = Monday; default every day)."""
    if unknown := set(params) - {"max_min", "weekdays"}:
        raise ValueError(f"daily_limit has unknown params {sorted(unknown)}")
    max_min = params.get("max_min")
    if not isinstance(max_min, int) or isinstance(max_min, bool) or max_min < 0:
        raise ValueError(f"daily_limit max_min must be a non-negative integer, got {max_min!r}")
    weekdays = params.get("weekdays", list(range(7)))
    if not isinstance(weekdays, list) or any(day not in range(7) for day in weekdays):
        raise ValueError(f"daily_limit weekdays must be a list of 0..6, got {weekdays!r}")
    return DailyLimit(max_min, tuple(sorted(set(weekdays))))


def _item_chunks(item: Item, kept: list[Block], old: list[Block], slot_min: int) -> list[Chunk]:
    """Chunks for one item. Old unlocked blocks pass their id and start to chunk i."""
    if not item.windows:
        return []  # not scheduled yet; stays in the task list

    if item.estimate_min is None:
        sizes = _fill_window_size(item, kept, slot_min)
    else:
        remaining = item.estimate_min - sum(covered_min(b) for b in kept)
        if remaining <= 0:
            return []
        total_slots = -(-remaining // slot_min)
        sizes = split_slots(total_slots, item.max_chunk_min, slot_min)

    chunks = []
    for i, size in enumerate(sizes):
        previous = old[i] if i < len(old) else None
        chunks.append(
            Chunk(
                item_id=item.id,
                block_id=previous.id if previous else uuid4(),
                size=size,
                candidates=_candidates(item, size, slot_min),
                previous_start=ceil_slot(previous.start, slot_min) if previous else None,
            )
        )
    return chunks


def _fill_window_size(item: Item, kept: list[Block], slot_min: int) -> list[int]:
    """An item without an estimate gets one block filling its single window exactly."""
    if len(item.windows) > 1:
        raise ValueError(
            f"Item {item.title!r} has no estimate_min but {len(item.windows)} windows; "
            "set an estimate"
        )
    if kept:
        return []
    window = item.windows[0]
    size = floor_slot(window.end, slot_min) - ceil_slot(window.start, slot_min)
    return [max(size, 1)]  # a window smaller than one slot yields no candidates


def split_slots(total: int, max_chunk_min: int | None, slot_min: int) -> list[int]:
    """Split `total` slots into the fewest near-equal chunks no longer than max_chunk_min.

    5h with a 2h max at 15-minute slots is 20 slots in 3 chunks: 7 + 7 + 6.
    """
    if max_chunk_min is None:
        return [total]
    max_slots = max(1, max_chunk_min // slot_min)
    count = -(-total // max_slots)
    base, extra = divmod(total, count)
    return [base + 1] * extra + [base] * (count - extra)


def _candidates(item: Item, size: int, slot_min: int) -> tuple[int, ...]:
    """Start slots where a block of `size` slots fits in a window and ends by the deadline.

    Window edges that are not on the slot grid are rounded inward.
    """
    latest_end = floor_slot(item.deadline, slot_min) if item.deadline else None
    starts: set[int] = set()
    for window in item.windows:
        first = ceil_slot(window.start, slot_min)
        end = floor_slot(window.end, slot_min)
        if latest_end is not None:
            end = min(end, latest_end)
        starts.update(range(first, end - size + 1))
    return tuple(sorted(starts))
