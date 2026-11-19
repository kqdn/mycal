"""Plan weeks from the database and store the result (Milestone 3).

Not part of the solver: a caller, like api.py and store.py. It loads items,
blocks, frames and constraints from the store, compiles windows, calls
solve() and saves what comes back. solve() itself is unchanged.

Spans. Weeks are planned together in spans of at most MAX_SPAN_WEEKS, in one
solve, so work due in a later week can start in an earlier one; the earlier
week score tier puts it in the earliest week with room. Only the first week
of a span is marked planned. The span's other weeks keep their new
blocks as their current plan and re-plan (stably) when viewed, so they can
take work due in the week after them.

Deferring. In a span, a "before a deadline" item due after the span's end is
deferred: it gets no windows, and its blocks stay put. It is placed by a span
that reaches its deadline week, so it only goes in the MAX_SPAN_WEEKS weeks up
to its deadline (a known limit).

Work that doesn't fit (Milestone 8). A span is solved with partial placement,
so it always gets a plan: when not all work fits, solve() places as much as
it can and the rest has no blocks. A week is never "can't be planned". Items
with work left over are listed in their due week with a reason, like "1h
won't fit before Fri 5pm" (left_over).

Series (Milestone 6). Before planning, the missing occurrences of every stored
series are created for the weeks being planned (create_occurrences), so a
weekly class shows up in every week it repeats in. Occurrences are never
created in the past: only ones with a day left from today on (for a days
item, one of its weekdays).

How blocks are passed to solve() for a span:
    - The span's planned, unlocked blocks that start at or after now, of items
      that aren't deferred, are the current plan. solve() may move them, and
      stability keeps them where they are unless something needs the room.
    - Everything else is kept (as locked copies if planned): blocks that
      already started, blocks outside the span, deferred items' blocks, and
      locked or finished blocks. Kept blocks count toward an item's remaining
      work without moving.
    - New blocks only go after now. Exact-time items still compile for the
      whole span, so a fixed event earlier in the week is placed (on its only
      spot) even when the week is first planned midway through.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from mycal import store
from mycal.model import Block, BlockStatus, FlexPreset, Item, Window, WorkFrame
from mycal.presets import compile_constraint, compile_windows, every_day_session
from mycal.recurrence import expand_series
from mycal.problem import ceil_slot, covered_min, floor_slot, session_min, slot_start
from mycal.settings import SolverSettings
from mycal.solve import SolveResult, solve
from mycal.windows import merge_windows, work_frame_windows

# The most weeks planned in one solve. Measured on five imported weeks with
# work_limit 10: two weeks solves to OPTIMAL (5.5 deterministic units), three
# or more hit the limit. See the PRD decision log.
MAX_SPAN_WEEKS = 2
WEEK = timedelta(weeks=1)


class PlannerTimeout(Exception):
    """CP-SAT hit the work limit before finding any arrangement: no proof either way, so nothing was saved."""


@dataclass(frozen=True, slots=True)
class Horizon:
    """A stretch of time as UTC moments, from a local Monday 00:00 to a later one."""

    start: datetime
    end: datetime


def week_horizon(week_start: date, timezone: str) -> Horizon:
    return span_horizon(week_start, week_start, timezone)


def span_horizon(first: date, last: date, timezone: str) -> Horizon:
    """From `first`'s Monday 00:00 to the Monday after `last`, local, as UTC."""
    zone = ZoneInfo(timezone)
    start = datetime.combine(first, time(), tzinfo=zone).astimezone(UTC)
    end = datetime.combine(last + WEEK, time(), tzinfo=zone).astimezone(UTC)
    return Horizon(start, end)


def plan_weeks(conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, now: datetime) -> None:
    """Plan every week in [first..last] in spans of at most MAX_SPAN_WEEKS, and store the plans.

    Work that doesn't fit is left without blocks (see left_over).
    """
    create_occurrences(conn, settings, first, last, now)
    week = first
    while week <= last:
        span_last = min(last, week + (MAX_SPAN_WEEKS - 1) * WEEK)
        _plan_span(conn, settings, week, span_last, now)
        week = span_last + WEEK


def create_occurrences(conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, now: datetime) -> None:
    """Store the missing occurrences of every series in the weeks [first..last], skipping the past.

    An occurrence is created only if it still has a day from today on: its
    date, or for a days item (repeating on Monday), any day of its week. So the
    past is never filled in, but this week's Gym still appears on a Wednesday.
    Each occurrence takes its series' source, so replacing that week file
    removes it too. Running it twice creates nothing new.
    """
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    items = store.list_items(conn, include_archived=True)  # an archived occurrence is never made again
    for series in store.list_series(conn):
        source = store.series_source(conn, series.id)
        for item in expand_series(series, items, first, last + timedelta(days=6)):
            if occurrence_last_day(item) >= today and _has_a_day_left(item, today):
                store.put_item(conn, item, source)


def _has_a_day_left(occurrence: Item, today: date) -> bool:
    """A days occurrence needs one of its weekdays from today on (a Mon/Wed/Fri Gym has none on Saturday)."""
    if occurrence.flex_preset is not FlexPreset.DAYS:
        return True
    assert occurrence.occurrence_date is not None
    week = monday(occurrence.occurrence_date)
    return any(week + timedelta(days=d) >= today for d in occurrence.preset_params["weekdays"])


def occurrence_last_day(occurrence: Item) -> date:
    """An occurrence's last local day: its date, or for a days item, the Sunday of its week."""
    assert occurrence.occurrence_date is not None
    if occurrence.flex_preset is FlexPreset.DAYS:
        return occurrence.occurrence_date + timedelta(days=6 - occurrence.occurrence_date.weekday())
    return occurrence.occurrence_date


@dataclass(slots=True)
class _Attempt:
    result: SolveResult
    current: list[Block]
    kept: list[Block]


def _plan_span(conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, now: datetime) -> None:
    """Plan one span with partial placement, store its blocks and mark its first week planned."""
    attempt = _solve_span(conn, settings, first, last, now)
    kept_ids = {b.id for b in attempt.kept}
    placed = [b for b in attempt.result.blocks if b.id not in kept_ids]
    store.save_plan(conn, [b.id for b in attempt.current], placed, {first: True}, now)


def _solve_span(conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, now: datetime) -> _Attempt:
    """One solve of the span [first..last], deferring deadline items due after it. Saves nothing."""
    span = span_horizon(first, last, settings.timezone)
    # New blocks only go after now, rounded up to the slot grid.
    open_from = max(span.start, open_from_moment(now, settings.slot_min))
    items = store.list_items(conn)
    deferred = {i.id for i in items if _due_after(i, span.end)}

    blocks = store.list_blocks(conn)
    frames = store.list_work_frames(conn)
    items = effective_items(items, blocks, frames, settings, now)

    current: list[Block] = []
    kept: list[Block] = []
    for block in blocks:
        in_span = block.start < span.end and block.end > span.start
        if in_span and block.item_id not in deferred and _is_current_plan(block, open_from):
            current.append(block)
        else:
            kept.append(_as_kept(block))  # stays put, still counts toward its item

    planned = [
        replace(item, windows=[] if item.id in deferred else _windows(item, frames, settings.timezone, span, open_from))
        for item in items
    ]
    constraints = [compile_constraint(c, settings.timezone, span.start, span.end) for c in store.list_constraints(conn)]
    try:
        result = solve(planned, kept + current, frames, constraints, settings)  # partial when not all fits
    except RuntimeError as error:  # the engine's "no arrangement within the work limit"
        raise PlannerTimeout(str(error)) from error
    return _Attempt(result, current, kept)


def _due_after(item: Item, moment: datetime) -> bool:
    return item.flex_preset is FlexPreset.BEFORE_DEADLINE and item.deadline is not None and item.deadline > moment


# Which weeks to plan


def span_for_view(conn: sqlite3.Connection, settings: SolverSettings, week_start: date, now: datetime) -> tuple[date, date]:
    """Viewing an unplanned week: it, through the latest deadline week of deadline items that can go in it (capped)."""
    week = week_horizon(week_start, settings.timezone)
    last = week_start
    for item in store.list_items(conn):
        if _due_after(item, max(week.start, now)) and item.deadline is not None:
            last = max(last, local_monday(item.deadline - timedelta(microseconds=1), settings.timezone))
    return week_start, min(last, week_start + (MAX_SPAN_WEEKS - 1) * WEEK)


def span_for_item(item: Item, timezone: str, now: datetime) -> tuple[date, date]:
    """The weeks to re-plan for a new item: its last week and up to MAX_SPAN_WEEKS - 1 before it."""
    touched = weeks_touched(item, timezone, now)
    last = touched[-1]
    return max(touched[0], last - (MAX_SPAN_WEEKS - 1) * WEEK), last


# Remaining work and waiting


def open_from_moment(now: datetime, slot_min: int) -> datetime:
    """The first slot boundary at or after now: new blocks only go from here."""
    return slot_start(ceil_slot(now, slot_min), slot_min)


def effective_item(
    item: Item, blocks: list[Block], frames: list[WorkFrame], settings: SolverSettings, now: datetime
) -> Item:
    """The item with the work it still has as of now. Read remaining work through this, never estimate_min.

    Lengths are stored as typed and rounded to the slot grid here, so the
    stored item never changes: estimate_min up, max_chunk_min down (at least
    one slot), an every-day session up. 20m is planned as 30m, and a 20m
    longest session as 15m.

    "Every one of these days" items also get their work recomputed: what their kept
    sessions cover (done, partial, locked, or already started, which the
    planner keeps) plus one session for each open day: a chosen day with no
    kept session and room for a whole session after now. So a day that passed
    without a session is simply missed, and no work moves to another day or
    week. max_chunk_min and one_block_per_day are set here too, so k sessions
    over k open days put exactly one on each.

    An "N times a week" item (any of these days, one block per day) that has
    more sessions left than days left in its week gets one session per day
    left (see Shortfall), instead of making its week unplannable.
    """
    slot = settings.slot_min
    session = every_day_session(item.preset_params) if item.flex_preset is FlexPreset.DAYS else None
    if session is None:
        rounded = _on_grid(item, slot)
        shortfall = _times_a_week_shortfall(rounded, blocks, frames, settings, now)
        if shortfall is None:
            return rounded
        return replace(rounded, estimate_min=shortfall.covered_min + shortfall.placeable_min)
    session = planned_up(session, slot)

    kept = _kept_of(item, blocks, now, slot)
    covered = [(b, covered_min(b)) for b in kept]
    kept_days = _days_of((b for b, minutes in covered if minutes > 0), settings.timezone)
    open_days = _open_days(item, frames, settings, now, session) - kept_days
    estimate = sum(minutes for _, minutes in covered) + session * len(open_days)
    return replace(item, estimate_min=estimate, max_chunk_min=session, one_block_per_day=True)


@dataclass(frozen=True, slots=True)
class Shortfall:
    """An "N times a week" item with fewer days left in its week than sessions to place.

    It is planned with one session per day left (placeable_min) instead of
    making the week unplannable. `sessions` is how many it would have had in
    all, `gets` how many it has now: those already held plus one per day left.
    """

    item_id: UUID
    title: str
    week: date  # the item's week (its Monday)
    sessions: int
    gets: int
    days_left: tuple[date, ...]
    covered_min: int
    placeable_min: int


def shortfalls(
    items: list[Item], blocks: list[Block], frames: list[WorkFrame], settings: SolverSettings, now: datetime
) -> list[Shortfall]:
    """The "N times a week" items that get fewer sessions than they need, by title."""
    found = []
    for item in items:
        if item.flex_preset is FlexPreset.DAYS and every_day_session(item.preset_params) is not None:
            continue  # every-day items already count only the days left
        shortfall = _times_a_week_shortfall(_on_grid(item, settings.slot_min), blocks, frames, settings, now)
        if shortfall is not None:
            found.append(shortfall)
    return sorted(found, key=lambda s: (s.title, str(s.item_id)))


def _on_grid(item: Item, slot_min: int) -> Item:
    """The item with its stored lengths rounded to the slot grid (see effective_item)."""
    return replace(
        item,
        estimate_min=None if item.estimate_min is None else planned_up(item.estimate_min, slot_min),
        max_chunk_min=None if item.max_chunk_min is None else planned_down(item.max_chunk_min, slot_min),
    )


def _times_a_week_shortfall(
    item: Item, blocks: list[Block], frames: list[WorkFrame], settings: SolverSettings, now: datetime
) -> Shortfall | None:
    """For an "N times a week" item (lengths already on the slot grid): its shortfall, or None if it fits.

    The sessions still to place need one day each, and a day is left when it
    is one of the item's days, has room for a whole session after now and
    holds no session of the item yet (the solver's one-block-per-day rule).
    """
    if item.flex_preset is not FlexPreset.DAYS or not item.one_block_per_day:
        return None
    if item.estimate_min is None or item.max_chunk_min is None:
        return None
    session = item.max_chunk_min
    kept = _kept_of(item, blocks, now, settings.slot_min)
    covered = sum(covered_min(b) for b in kept)
    remaining = item.estimate_min - covered
    if remaining <= 0:
        return None
    held_days = _days_of((b for b in kept if session_min(b) > 0), settings.timezone)
    days_left = _open_days(item, frames, settings, now, session) - held_days
    if -(-remaining // session) <= len(days_left):
        return None
    held = sum(1 for b in kept if session_min(b) > 0)
    return Shortfall(
        item_id=item.id,
        title=item.title,
        week=item.preset_params["week"],
        sessions=-(-item.estimate_min // session),
        gets=held + len(days_left),
        days_left=tuple(sorted(days_left)),
        covered_min=covered,
        placeable_min=session * len(days_left),
    )


def _kept_of(item: Item, blocks: list[Block], now: datetime, slot_min: int) -> list[Block]:
    """The item's blocks the planner keeps as they are (see _solve_span), as it keeps them."""
    open_from = open_from_moment(now, slot_min)
    return [_as_kept(b) for b in blocks if b.item_id == item.id and not _is_current_plan(b, open_from)]


def _open_days(item: Item, frames: list[WorkFrame], settings: SolverSettings, now: datetime, session: int) -> set[date]:
    """A days item's local days in its week with room for one whole session after now."""
    slot = settings.slot_min
    zone = ZoneInfo(settings.timezone)
    week = week_horizon(item.preset_params["week"], settings.timezone)
    windows = _windows(item, frames, settings.timezone, week, open_from_moment(now, slot))
    return {
        w.start.astimezone(zone).date()
        for w in windows
        if floor_slot(w.end, slot) - ceil_slot(w.start, slot) >= session // slot
    }


def _days_of(blocks: Iterable[Block], timezone: str) -> set[date]:
    zone = ZoneInfo(timezone)
    return {b.start.astimezone(zone).date() for b in blocks}


def planned_up(minutes: int, slot_min: int) -> int:
    """A length rounded up to the slot grid: 20m is planned as 30m."""
    return -(-minutes // slot_min) * slot_min


def planned_down(minutes: int, slot_min: int) -> int:
    """A longest session rounded down to the slot grid, but never below one slot."""
    return max(1, minutes // slot_min) * slot_min


def effective_items(
    items: list[Item], blocks: list[Block], frames: list[WorkFrame], settings: SolverSettings, now: datetime
) -> list[Item]:
    return [effective_item(item, blocks, frames, settings, now) for item in items]


def _as_kept(block: Block) -> Block:
    """How the planner keeps a block that isn't part of the current plan: planned ones become locked."""
    if block.status is BlockStatus.PLANNED and not block.locked:
        return replace(block, locked=True)
    return block


def placed_min(item: Item, blocks: list[Block]) -> int:
    """Minutes of the item's work its blocks cover, in every week: planned blocks count their
    length, finished ones what they covered (covered_min)."""
    return sum(
        (b.end - b.start) // timedelta(minutes=1) if b.status is BlockStatus.PLANNED else covered_min(b)
        for b in blocks
        if b.item_id == item.id
    )


def remaining_min(item: Item, blocks: list[Block]) -> int:
    """Minutes of the item's work not covered by its blocks. An item without an estimate needs one block."""
    if item.estimate_min is None:
        return 0 if any(b.item_id == item.id for b in blocks) else 1
    return max(0, item.estimate_min - placed_min(item, blocks))


def due_week(item: Item, timezone: str) -> date | None:
    """The week an item's work belongs to at the latest, or None if it has no such week."""
    params = item.preset_params
    if item.flex_preset is FlexPreset.BEFORE_DEADLINE and item.deadline is not None:
        return local_monday(item.deadline - timedelta(microseconds=1), timezone)
    if item.flex_preset is FlexPreset.DAYS:
        return params["week"]
    if item.flex_preset in (FlexPreset.DAY, FlexPreset.DAY_RANGE):
        return monday(params["day"])
    if item.flex_preset is FlexPreset.EXACT:
        return local_monday(params["start"], timezone)
    return None


def left_over_min(
    conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, now: datetime
) -> dict[UUID, tuple[Item, int]]:
    """Items due in the weeks [first..last] with work that has no blocks, and how many minutes.

    Only accurate once those weeks are planned: an item due in a week that was
    never planned has no blocks yet. Items due later are left out, since a
    later span places them. Fixed events (no estimate) always get their block.
    """
    blocks = store.list_blocks(conn)
    frames = store.list_work_frames(conn)
    found: dict[UUID, tuple[Item, int]] = {}
    for item in effective_items(store.list_items(conn), blocks, frames, settings, now):
        due = _last_week(item, settings.timezone, now)
        if item.estimate_min is None or due is None or not first <= due <= last:
            continue
        if (minutes := remaining_min(item, blocks)) > 0:
            found[item.id] = (item, minutes)
    return found


def left_over(conn: sqlite3.Connection, settings: SolverSettings, week_start: date, now: datetime) -> dict[UUID, str]:
    """Items shown in this week's Unscheduled list because some of their work didn't fit, with the reason."""
    return {
        item_id: left_over_message(item, minutes, settings.timezone)
        for item_id, (item, minutes) in left_over_min(conn, settings, week_start, week_start, now).items()
    }


def left_over_message(item: Item, minutes: int, timezone: str) -> str:
    """"1h 30m won't fit before Fri 5pm", "45m won't fit on Wed" or "2h won't fit on its days"."""
    amount = duration_text(minutes)
    params = item.preset_params
    if item.flex_preset is FlexPreset.BEFORE_DEADLINE and item.deadline is not None:
        due = item.deadline.astimezone(ZoneInfo(timezone))
        return f"{amount} won't fit before {due:%a} {clock_text(due.time())}"
    if item.flex_preset in (FlexPreset.DAY, FlexPreset.DAY_RANGE):
        return f"{amount} won't fit on {params['day']:%a}"
    if item.flex_preset is FlexPreset.DAYS:
        return f"{amount} won't fit on its days"
    return f"{amount} won't fit in its time"


def duration_text(minutes: int) -> str:
    """90 is "1h 30m", 60 is "1h", 45 is "45m"."""
    hours, rest = divmod(minutes, 60)
    return " ".join(part for part in (f"{hours}h" if hours else "", f"{rest}m" if rest else "") if part) or "0m"


def clock_text(moment: time) -> str:
    """17:00 is "5pm", 9:30 is "9:30am", 0:00 is "12am"."""
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}{suffix}" if moment.minute == 0 else f"{hour}:{moment.minute:02d}{suffix}"


def _last_week(item: Item, timezone: str, now: datetime) -> date | None:
    """The week an item's work belongs to at the latest (due_week), or for a Custom item, its last painted week."""
    due = due_week(item, timezone)
    if due is None and item.flex_preset is FlexPreset.CUSTOM:
        touched = weeks_touched(item, timezone, now)
        due = touched[-1] if touched else None
    return due


def week_title(week_start: date) -> str:
    """"Nov 16 to 22", or "Nov 30 to Dec 6" across months, like the page title."""
    end = week_start + timedelta(days=6)
    start_text = f"{week_start:%b} {week_start.day}"
    end_text = f"{end.day}" if end.month == week_start.month else f"{end:%b} {end.day}"
    return f"{start_text} to {end_text}"


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def local_monday(moment: datetime, timezone: str) -> date:
    """The Monday of the local week a UTC moment falls in."""
    return monday(moment.astimezone(ZoneInfo(timezone)).date())


def weeks_touched(item: Item, timezone: str, now: datetime) -> list[date]:
    """The Mondays of the weeks an item's windows can fall in (it can't be placed before now)."""
    params = item.preset_params
    last_moment = timedelta(microseconds=1)  # an end moment belongs to the week before it
    if item.flex_preset is FlexPreset.EXACT:
        return sorted({local_monday(params["start"], timezone), local_monday(params["end"] - last_moment, timezone)})
    if item.flex_preset in (FlexPreset.DAY, FlexPreset.DAY_RANGE):
        day: date = params["day"]
        overnight = item.flex_preset is FlexPreset.DAY_RANGE and params["end_time"] <= params["start_time"]
        return sorted({monday(day), monday(day + timedelta(days=1 if overnight else 0))})
    if item.flex_preset is FlexPreset.DAYS:
        return [params["week"]]
    if item.flex_preset is FlexPreset.BEFORE_DEADLINE and item.deadline is not None:
        first, last = local_monday(now, timezone), local_monday(item.deadline - last_moment, timezone)
        return [first + timedelta(weeks=n) for n in range((last - first).days // 7 + 1)]
    if item.flex_preset is FlexPreset.CUSTOM:
        return sorted({local_monday(w.start, timezone) for w in params.get("windows", [])})
    return []


def weeks_of_blocks(blocks: list[Block], timezone: str) -> list[date]:
    """The Mondays of the weeks the blocks start or end in."""
    last_moment = timedelta(microseconds=1)
    return sorted(
        {local_monday(b.start, timezone) for b in blocks} | {local_monday(b.end - last_moment, timezone) for b in blocks}
    )


def _is_current_plan(block: Block, open_from: datetime) -> bool:
    return block.status is BlockStatus.PLANNED and not block.locked and block.start >= open_from


def _windows(item: Item, frames: list[WorkFrame], timezone: str, week: Horizon, open_from: datetime) -> list[Window]:
    """The item's windows this week. Flexible ones start no earlier than `open_from`."""
    windows = compile_windows(item, frames, timezone, week.start, week.end)
    if item.flex_preset is FlexPreset.EXACT:
        return windows
    return [Window(max(w.start, open_from), w.end) for w in windows if w.end > open_from]


def frame_spans(frames: list[WorkFrame], week_start: date, timezone: str) -> list[Window]:
    """The week's work-frame time as merged UTC windows, clipped to the week.

    Starts a day early so an overnight frame from the Sunday before still
    shows its tail on Monday morning.
    """
    week = week_horizon(week_start, timezone)
    windows = [
        w
        for frame in frames
        for w in work_frame_windows(frame, week_start - timedelta(days=1), week_start + timedelta(days=6))
    ]
    clipped = [Window(max(w.start, week.start), min(w.end, week.end)) for w in windows if w.end > week.start and w.start < week.end]
    return merge_windows(clipped)
