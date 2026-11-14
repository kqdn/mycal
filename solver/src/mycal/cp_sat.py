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
most one per item per day".
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import cache
from uuid import UUID
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from mycal.model import Block
from mycal.problem import Chunk, Problem, ceil_slot, covered_min, floor_slot, slot_start

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
