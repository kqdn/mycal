"""Plan weeks from the database and store the result (Milestone 3).

Not part of the solver: a caller, like api.py and store.py. It loads items,
blocks, frames and constraints from the store, compiles windows, calls
solve() and saves what comes back. solve() itself is unchanged.

Spans. Weeks are planned together in spans of at most MAX_SPAN_WEEKS, in one
solve, so work due in a later week can start in an earlier one; the earlier
week score tier puts it in the earliest week with room. Only the first week
of a span that fits is marked planned. The span's other weeks keep their new
blocks as their current plan and re-plan (stably) when viewed, so they can
take work due in the week after them.

Deferring. In a span, a "before a deadline" item due after the span's end is
deferred: it gets no windows, and its blocks stay put. It is placed by a span
that reaches its deadline week, so it only goes in the MAX_SPAN_WEEKS weeks up
to its deadline (a known limit).

Broken weeks. A joint solve is all or nothing, so a week that can't be planned
would sink every span holding it. A span that doesn't fit is shortened from
the end, first with every item it reaches required, then with the items due
after the shorter span deferred. The longest span that fits is saved; the
week right after it is the broken one and is marked infeasible on its own,
keeping its old blocks; planning then continues after it as a joint span
again. Items left waiting on a broken week are listed with a reason.

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
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from mycal import store
from mycal.model import Block, BlockStatus, FlexPreset, Item, Window, WorkFrame
from mycal.presets import compile_constraint, compile_windows
from mycal.problem import ceil_slot, covered_min, slot_start
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


def plan_weeks(
    conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, now: datetime
) -> dict[date, bool]:
    """Plan every week in [first..last] in spans of at most MAX_SPAN_WEEKS, and store the plans.

    After a week that can't be planned, a fresh span starts at the next week, so
    planning resumes jointly rather than one week at a time. Returns each week's
    outcome: True if it fit (as part of a span), False if it can't be planned.
    """
    outcome: dict[date, bool] = {}
    week = first
    while week <= last:
        span_outcome, week = _plan_span(conn, settings, week, min(last, week + (MAX_SPAN_WEEKS - 1) * WEEK), now)
        outcome |= span_outcome
    return outcome


@dataclass(slots=True)
class _Attempt:
    result: SolveResult
    current: list[Block]
    kept: list[Block]


def _plan_span(
    conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, now: datetime
) -> tuple[dict[date, bool], date]:
    """Plan one span, shortening it around a broken week. Returns the outcome and the week to continue from."""
    outer_end = span_horizon(first, last, settings.timezone).end  # items due later are always deferred
    k = last
    while k >= first:
        span_end = span_horizon(first, k, settings.timezone).end
        for defer_after in dict.fromkeys([outer_end, span_end]):  # required first, then deferred
            attempt = _solve_span(conn, settings, first, k, now, defer_after)
            if attempt.result.feasible:
                kept_ids = {b.id for b in attempt.kept}
                placed = [b for b in attempt.result.blocks if b.id not in kept_ids]
                store.save_plan(conn, [b.id for b in attempt.current], placed, {first: True}, now)
                outcome = {first + n * WEEK: True for n in range((k - first).days // 7 + 1)}
                if k == last:
                    return outcome, last + WEEK
                broken = k + WEEK  # the week right after the span that fits can't be planned
                _mark(conn, {broken: False}, now)
                return outcome | {broken: False}, broken + WEEK
        k -= WEEK
    _mark(conn, {first: False}, now)  # not even the first week alone fits
    return {first: False}, first + WEEK


def _mark(conn: sqlite3.Connection, marks: dict[date, bool], now: datetime) -> None:
    store.save_plan(conn, [], [], marks, now)


def _solve_span(
    conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, now: datetime, defer_after: datetime
) -> _Attempt:
    """One solve of the span [first..last], deferring deadline items due after `defer_after`. Saves nothing."""
    span = span_horizon(first, last, settings.timezone)
    # New blocks only go after now, rounded up to the slot grid.
    open_from = max(span.start, slot_start(ceil_slot(now, settings.slot_min), settings.slot_min))
    items = store.list_items(conn)
    deferred = {i.id for i in items if _due_after(i, defer_after)}

    current: list[Block] = []
    kept: list[Block] = []
    for block in store.list_blocks(conn):
        in_span = block.start < span.end and block.end > span.start
        if in_span and block.item_id not in deferred and _is_current_plan(block, open_from):
            current.append(block)
        elif block.status is BlockStatus.PLANNED and not block.locked:
            kept.append(replace(block, locked=True))  # stays put, still counts toward its item
        else:
            kept.append(block)

    frames = store.list_work_frames(conn)
    planned = [
        replace(item, windows=[] if item.id in deferred else _windows(item, frames, settings.timezone, span, open_from))
        for item in items
    ]
    constraints = [compile_constraint(c, settings.timezone, span.start, span.end) for c in store.list_constraints(conn)]
    try:
        result = solve(planned, kept + current, frames, constraints, settings)
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


def remaining_min(item: Item, blocks: list[Block]) -> int:
    """Minutes of the item's work not covered by its blocks. An item without an estimate needs one block."""
    mine = [b for b in blocks if b.item_id == item.id]
    if item.estimate_min is None:
        return 0 if mine else 1
    covered = sum(
        (b.end - b.start) // timedelta(minutes=1) if b.status is BlockStatus.PLANNED else covered_min(b) for b in mine
    )
    return max(0, item.estimate_min - covered)


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


def waiting_on_broken_weeks(conn: sqlite3.Connection, timezone: str, week_start: date) -> dict[UUID, str]:
    """Items shown in this week's Unscheduled list because their work waits on a week that can't be planned.

    Only broken weeks count: items deferred by the span cap are normal and not listed.
    An item is listed in its broken week and the MAX_SPAN_WEEKS - 1 weeks before it.
    """
    blocks = store.list_blocks(conn)
    reasons: dict[UUID, str] = {}
    for item in store.list_items(conn):
        due = due_week(item, timezone)
        if due is None or not (due - (MAX_SPAN_WEEKS - 1) * WEEK <= week_start <= due):
            continue
        if store.plan_status(conn, due) is False and remaining_min(item, blocks) > 0:
            reasons[item.id] = f"Waiting on {week_title(due)}, which can't be planned."
    return reasons


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
