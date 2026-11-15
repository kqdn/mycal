"""Plan one week from the database and store the result (Milestone 3).

Not part of the solver: a caller, like api.py and store.py. It loads items,
blocks, frames and constraints from the store, compiles windows for the week,
calls solve() and saves what comes back.

How blocks are passed to solve() when re-planning week W:
    - W's planned, unlocked blocks that start at or after now are the current
      plan. solve() may move them, and stability keeps them where they are
      unless something needs the room.
    - Everything else is kept: blocks that already started, blocks in other
      weeks (passed as locked copies, so they count toward an item's
      remaining work without moving), and locked or finished blocks.
    - New blocks only go after now. Exact-time items still compile for the
      whole week, so a fixed event earlier in the week is placed (on its only
      spot) even when the week is first planned midway through.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mycal import store
from mycal.model import Block, BlockStatus, FlexPreset, Item, Window, WorkFrame
from mycal.presets import compile_constraint, compile_windows
from mycal.problem import ceil_slot, slot_start
from mycal.settings import SolverSettings
from mycal.solve import SolveResult, solve
from mycal.windows import merge_windows, work_frame_windows


@dataclass(frozen=True, slots=True)
class Horizon:
    """A week as UTC moments: local Monday 00:00 to the next Monday 00:00."""

    start: datetime
    end: datetime


def week_horizon(week_start: date, timezone: str) -> Horizon:
    zone = ZoneInfo(timezone)
    start = datetime.combine(week_start, time(), tzinfo=zone).astimezone(UTC)
    end = datetime.combine(week_start + timedelta(days=7), time(), tzinfo=zone).astimezone(UTC)
    return Horizon(start, end)


def plan_week(conn: sqlite3.Connection, settings: SolverSettings, week_start: date, now: datetime) -> SolveResult:
    """Re-plan the week from what the database holds, store the new plan, and return the solve result.

    When nothing fits, the old blocks stay and the week is marked infeasible.
    """
    week = week_horizon(week_start, settings.timezone)
    # New blocks only go after now, rounded up to the slot grid.
    open_from = max(week.start, slot_start(ceil_slot(now, settings.slot_min), settings.slot_min))

    current: list[Block] = []
    kept: list[Block] = []
    for block in store.list_blocks(conn):
        in_week = block.start < week.end and block.end > week.start
        if in_week and _is_current_plan(block, open_from):
            current.append(block)
        elif block.status is BlockStatus.PLANNED and not block.locked:
            kept.append(replace(block, locked=True))  # stays put, still counts toward its item
        else:
            kept.append(block)

    frames = store.list_work_frames(conn)
    items = [
        replace(item, windows=_windows(item, frames, settings.timezone, week, open_from))
        for item in store.list_items(conn)
    ]
    constraints = [compile_constraint(c, settings.timezone, week.start, week.end) for c in store.list_constraints(conn)]

    result = solve(items, kept + current, frames, constraints, settings)

    kept_ids = {b.id for b in kept}
    placed = [b for b in result.blocks if b.id not in kept_ids]
    drop = [b.id for b in current] if result.feasible else []
    store.save_plan(conn, week_start, drop, placed, result.feasible, now)
    return result


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
