"""OR-Tools CP-SAT engine.

Each chunk gets a start variable whose domain is its candidate start slots
(windows and deadline are already built in), plus an interval variable
[start, start + size). One NoOverlap constraint covers all the intervals.
Kept blocks are fixed, so instead of adding them as intervals, any start that
would overlap one is removed from the domain up front.

Each chunk also gets one true/false variable per local day it could start on;
exactly one is true, and when it is, the start must be one of that day's
candidates. This is reification: a constraint that only holds when a boolean
is true (OnlyEnforceIf). The day variables express one_block_per_day as "at
most one per item per day" and daily limits as "minutes on this day at most
the limit", and make the score below linear.

Score, minimized, in strict priority order (each tier's weight is larger
than the most the tiers below it can ever add up to, so a higher priority
always wins):
    1. stability: blocks moved away from their current start
    2. spread: extra blocks of the same item on one local day
    3. balance: the fullest local day, as load / work-frame minutes, kept
       blocks included (a day with no work frame is left out)
    4. earlier in the frame: slots from the start of the work-frame
       occurrence (else the item window) holding each block's start
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from functools import cache
from uuid import UUID
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from mycal.model import Block, Window
from mycal.problem import (
    Chunk,
    Problem,
    ceil_slot,
    covered_min,
    day_limit_min,
    floor_slot,
    kept_minutes_by_day,
    slot_start,
)
from mycal.windows import day_capacity_min, work_frame_windows

Interval = tuple[int, int]


def search(problem: Problem) -> list[Block] | None:
    """Return new blocks for every chunk, or None if CP-SAT proves no arrangement fits.

    Raises RuntimeError if the time limit runs out before any arrangement is
    found, since that is not a proof of infeasibility.
    """
    chunks = problem.chunks
    items = problem.items
    settings = problem.settings
    slot_min = settings.slot_min
    zone = ZoneInfo(settings.timezone)

    @cache
    def local_day(slot: int) -> date:
        return slot_start(slot, slot_min).astimezone(zone).date()

    busy: list[Interval] = []
    kept_by_item: dict[UUID, list[Interval]] = defaultdict(list)
    kept_days: dict[UUID, set[date]] = defaultdict(set)
    for block in problem.kept:
        interval = (floor_slot(block.start, slot_min), ceil_slot(block.end, slot_min))
        busy.append(interval)
        kept_by_item[block.item_id].append(interval)
        if covered_min(block) > 0:
            kept_days[block.item_id].add(local_day(interval[0]))

    dependents: dict[UUID, list[UUID]] = defaultdict(list)
    for item in items.values():
        for dep in item.depends_on:
            dependents[dep].append(item.id)

    def allowed(chunk: Chunk, start: int) -> bool:
        """Checks against fixed things only: kept blocks and their days."""
        end = start + chunk.size
        item = items[chunk.item_id]
        if any(a < end and start < b for a, b in busy):
            return False
        if any(b > start for dep in item.depends_on for _, b in kept_by_item[dep]):
            return False
        if any(a < end for later in dependents[chunk.item_id] for a, _ in kept_by_item[later]):
            return False
        return not (item.one_block_per_day and local_day(start) in kept_days[chunk.item_id])

    model = cp_model.CpModel()
    starts: list[cp_model.IntVar] = []
    intervals: list[cp_model.IntervalVar] = []
    day_vars: list[dict[date, cp_model.IntVar]] = []

    for i, chunk in enumerate(chunks):
        values = [s for s in chunk.candidates if allowed(chunk, s)]
        if not values:
            return None
        start = model.new_int_var_from_domain(cp_model.Domain.from_values(values), f"start_{i}")
        starts.append(start)
        intervals.append(model.new_fixed_size_interval_var(start, chunk.size, f"block_{i}"))

        by_day: dict[date, list[int]] = defaultdict(list)
        for s in values:
            by_day[local_day(s)].append(s)
        days: dict[date, cp_model.IntVar] = {}
        for day, day_values in by_day.items():
            on_day = model.new_bool_var(f"chunk_{i}_on_{day}")
            model.add_linear_expression_in_domain(
                start, cp_model.Domain.from_values(day_values)
            ).only_enforce_if(on_day)
            days[day] = on_day
        model.add_exactly_one(days.values())
        day_vars.append(days)

    model.add_no_overlap(intervals)

    chunks_of: dict[UUID, list[int]] = defaultdict(list)
    for i, chunk in enumerate(chunks):
        chunks_of[chunk.item_id].append(i)

    for item_id, mine in chunks_of.items():
        item = items[item_id]
        # Dependencies between chunks: start after every chunk of each dependency ends.
        for dep in item.depends_on:
            for i in mine:
                for j in chunks_of.get(dep, []):
                    model.add(starts[i] >= starts[j] + chunks[j].size)
        # Symmetry breaking: equal-size chunks of one item start in index order.
        for i, j in zip(mine, mine[1:]):
            if chunks[i].size == chunks[j].size:
                model.add(starts[i] < starts[j])
        if item.one_block_per_day:
            for day in {d for i in mine for d in day_vars[i]}:
                model.add_at_most_one(day_vars[i][day] for i in mine if day in day_vars[i])

    # Daily limits: placed minutes on a day fit in what kept blocks leave free.
    # If kept blocks alone are over, nothing more goes there (not infeasible).
    kept_min = kept_minutes_by_day(problem.kept, settings.timezone)
    for day in {d for vars_ in day_vars for d in vars_}:
        limit = day_limit_min(problem.daily_limits, day)
        if limit is not None:
            placed = sum(chunks[i].size * vars_[day] for i, vars_ in enumerate(day_vars) if day in vars_)
            model.add(slot_min * placed <= max(0, limit - kept_min[day]))

    _add_score(model, problem, starts, day_vars, chunks_of, busy, local_day)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.time_limit_s
    solver.parameters.num_workers = 1  # deterministic: same week, same schedule
    solver.parameters.random_seed = 0
    status = solver.solve(model)

    if status == cp_model.INFEASIBLE:
        return None
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"CP-SAT found no arrangement within {settings.time_limit_s}s "
            f"(status {solver.status_name(status)})"
        )

    return [
        Block(
            item_id=chunk.item_id,
            start=slot_start(solver.value(starts[i]), slot_min),
            end=slot_start(solver.value(starts[i]) + chunk.size, slot_min),
            id=chunk.block_id,
        )
        for i, chunk in enumerate(chunks)
    ]


def _add_score(
    model: cp_model.CpModel,
    problem: Problem,
    starts: list[cp_model.IntVar],
    day_vars: list[dict[date, cp_model.IntVar]],
    chunks_of: dict[UUID, list[int]],
    busy: list[Interval],
    local_day: Callable[[int], date],
) -> None:
    """Add the four score terms and minimize them in priority order."""
    chunks = problem.chunks
    slot_min = problem.settings.slot_min
    zone = ZoneInfo(problem.settings.timezone)

    # 1. Stability: a chunk is "moved" unless it starts where its old block did.
    moved = []
    for i, chunk in enumerate(chunks):
        if chunk.previous_start is None:
            continue
        model.add_hint(starts[i], chunk.previous_start)
        is_moved = model.new_bool_var(f"moved_{i}")
        model.add(starts[i] == chunk.previous_start).only_enforce_if(~is_moved)
        moved.append(is_moved)

    # 2. Spread: per item and day, blocks beyond the first (kept blocks count too).
    kept_count: dict[tuple[UUID, date], int] = defaultdict(int)
    for block in problem.kept:
        kept_count[(block.item_id, block.start.astimezone(zone).date())] += 1
    extras = []
    for item_id, mine in chunks_of.items():
        if problem.items[item_id].one_block_per_day:
            continue  # already at most one per day
        for day in {d for i in mine for d in day_vars[i]}:
            on_day = [day_vars[i][day] for i in mine if day in day_vars[i]]
            existing = kept_count[(item_id, day)]
            if len(on_day) + existing < 2:
                continue
            extra = model.new_int_var(0, len(on_day), f"extra_{item_id}_{day}")
            model.add(extra >= sum(on_day) + existing - 1)
            extras.append(extra)

    # 3. Balance: the fullest day, in thousandths of that day's work-frame minutes.
    #    "fullest >= load / capacity" is a division, but capacity is a constant per
    #    day, so it multiplies out to the linear "fullest * capacity >= 1000 * load".
    #    Days with no work-frame time have no capacity and are left out.
    days = {d for vars_ in day_vars for d in vars_}
    kept_load: dict[date, int] = defaultdict(int)
    for a, b in busy:
        kept_load[local_day(a)] += b - a
    capacity = {day: day_capacity_min(problem.work_frames, day, problem.settings.timezone) for day in days}
    total_min = (sum(c.size for c in chunks) + sum(kept_load.values())) * slot_min
    smallest = min((c for c in capacity.values() if c > 0), default=0)
    max_fullest = 1000 * total_min // smallest + 1 if smallest else 0
    fullest = model.new_int_var(0, max_fullest, "fullest_day")
    for day in days:
        if capacity[day] == 0:
            continue
        load = sum(chunks[i].size * vars_[day] for i, vars_ in enumerate(day_vars) if day in vars_)
        model.add(fullest * capacity[day] >= 1000 * slot_min * (load + kept_load[day]))

    # 4. Earlier in the frame: slots from the start of the work-frame occurrence
    #    holding each start, so a 12pm to 2am frame prefers 12pm over 12am. The
    #    whole occurrence counts, even the part before the planning week, and a
    #    start outside every frame counts from the start of its item window.
    #    The anchor changes from frame to frame, so "start minus anchor" is not
    #    linear; a table constraint lists the allowed (start, offset) pairs.
    all_starts = [s for c in chunks for s in c.candidates]
    frames: list[Interval] = []
    if all_starts:
        first, last = local_day(min(all_starts)), local_day(max(all_starts))
        frames = _spans(
            [w for f in problem.work_frames for w in work_frame_windows(f, first - timedelta(days=1), last)],
            slot_min,
        )
    offsets = []
    max_offset_total = 0
    for i, chunk in enumerate(chunks):
        own = _spans(problem.items[chunk.item_id].windows, slot_min)
        pairs = [(s, s - _anchor_of(s, frames, own)) for s in chunk.candidates]
        max_offset = max(o for _, o in pairs)
        max_offset_total += max_offset
        offset = model.new_int_var(0, max_offset, f"offset_{i}")
        model.add_allowed_assignments([starts[i], offset], pairs)
        offsets.append(offset)

    # Tier weights: each exceeds the largest possible total of all tiers below it.
    w_offset = 1
    w_balance = w_offset * (max_offset_total + 1)
    w_spread = w_balance * (max_fullest + 1)
    w_stability = w_spread * (len(chunks) + 1)
    model.minimize(
        w_stability * sum(moved)
        + w_spread * sum(extras)
        + w_balance * fullest
        + w_offset * sum(offsets)
    )


def _spans(windows: list[Window], slot_min: int) -> list[Interval]:
    """Each window as (first start slot, end slot), sorted by start."""
    return sorted((ceil_slot(w.start, slot_min), floor_slot(w.end, slot_min)) for w in windows)


def _anchor_of(slot: int, frames: list[Interval], own: list[Interval]) -> int:
    """First slot of the earliest frame occurrence holding `slot`, else of its item window."""
    for a, b in frames + own:
        if a <= slot < b:
            return a
    return slot
