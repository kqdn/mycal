"""OR-Tools CP-SAT engine.

Each chunk gets a start variable whose domain is its candidate start slots
(windows and deadline are already built in), plus an interval variable
[start, start + size). One NoOverlap constraint covers all the intervals.
Kept blocks and fixed events never move, so instead of adding them as
intervals, any start that would overlap a slot they touch is removed from the
domain up front.

Each chunk also gets one true/false variable per local day it could start on;
exactly one is true, and when it is, the start must be one of that day's
candidates. This is reification: a constraint that only holds when a boolean
is true (OnlyEnforceIf). The day variables express one_block_per_day as "at
most one per item per day" and daily limits as "minutes on this day at most
the limit", and make the score below linear.

Score, minimized, in strict priority order. Each tier's weight is at least
the most all lower tiers can add up to, plus the slack, plus one, so a plan
that is worse in any higher tier always scores more than `slack` above the
best plan:
    1. stability: blocks moved away from their current start
    2. spread: extra blocks of the same item on one local day
    3. preferences: weighted soft constraints (time_preference: a block's
       slots on the wrong side of its preferred or avoided windows;
       rest_between: sessions too few days apart)
    4. earlier week: each block's slots times how many weeks after the first
       week it starts in. It only picks the week; within a week the tiers
       below pick the day. So work lands in the earliest week with room and
       spills into a later week only when it has to. A one-week solve has
       nothing to choose here.
    5. balance: the fullest local day, as load / work-frame minutes, kept
       blocks included (a day with no work frame is left out)
    6. earlier in the frame: slots from the start of the work-frame
       occurrence (else the item window) holding each block's start

Partial placement (only when the full model is infeasible) takes two solves,
most important goal first (a lexicographic solve):
    1. Shrink: a separate model where each chunk also gets a size variable
       from 0 to its full size. The score is the slots left out, and on a
       tie the current blocks moved or cut (stability), so new work doesn't
       push out work that already has its place.
       A block keeps its start and loses slots from the end, and size 0
       leaves it out (an optional interval, whose `present` boolean is true
       when size is at least 1). For each start slot a table gives the most
       slots that fit there before the window closes, the deadline or a kept
       block, and the size stays within it. The day booleans add up to
       `present` instead of to one, and a chunk's slots on a day become a
       "size on day d" variable that is 0 unless the chunk starts on d,
       which keeps daily limits linear.
    2. Place: the ordinary model above, on the chunks cut to the sizes the
       first solve chose (left-out chunks dropped), with its plan as a hint.
The first solve settles how much fits, the second scores where it goes.
Putting "slots left out" on top of the six tiers in one model makes its
weight so large that the gap limit never stops the search: on an overfull
sample week that ran out the work limit twice over and still left out more.

Stopping is deterministic: one worker, a fixed seed, no wall-clock limit.
CP-SAT stops when it proves its plan is within `slack` of the best (the gap
limit), where slack is earliness_slack_min per flexible block, in slots.
Because of the weights above, only tier 6 can come out worse, and by at most
`slack` slots summed over the week. Proving the exact tier-5 optimum can take
minutes, since many arrangements tie in the tiers above. A deterministic
work limit is the backstop. Same input and same OR-Tools version, same plan.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from functools import cache
from uuid import UUID
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from mycal.model import Block, Window
from mycal.problem import (
    Chunk,
    Problem,
    SearchResult,
    TimePreference,
    ceil_slot,
    day_limit_min,
    floor_slot,
    kept_minutes_by_day,
    session_min,
    shrink_caps,
    slot_start,
    start_candidates,
)
from mycal.windows import day_capacity_min, work_frame_windows

Interval = tuple[int, int]


@dataclass(slots=True)
class BuiltModel:
    """The CP-SAT model for a problem: one start variable per chunk, and the slack in slots.

    `chunks` are the chunks in the model, in the order of `starts`. A partial
    model leaves out chunks with no room at all and has a size variable per chunk.
    """

    model: cp_model.CpModel
    starts: list[cp_model.IntVar]
    slack: int
    chunks: list[Chunk] = field(default_factory=list)
    sizes: list[cp_model.IntVar] = field(default_factory=list)


def search(problem: Problem, partial: bool = False) -> SearchResult:
    """Return new blocks for every chunk, or no blocks if CP-SAT proves no arrangement fits.

    With `partial`, return blocks for as much of the work as fits, in two
    solves (see the module docstring), each with the full work limit. The
    status is FEASIBLE if either solve stopped before proving its answer.

    Raises RuntimeError if the work limit runs out before any arrangement is
    found, since that is not a proof of infeasibility.
    """
    hints: list[int] = []
    shrink_status = "OPTIMAL"
    if partial:
        problem, hints, shrink_status = _shrink(problem)
    built = build_model(problem)
    if built is None:
        return SearchResult(None, "INFEASIBLE")
    if hints:
        built.model.clear_hints()  # stage 1's plan replaces the previous-start hints
        for start, hint in zip(built.starts, hints):
            built.model.add_hint(start, hint)

    solver, status = _run(built.model, problem.settings.work_limit, built.slack)
    if status == "INFEASIBLE":
        return SearchResult(None, "INFEASIBLE")
    slot_min = problem.settings.slot_min
    blocks = [
        Block(
            item_id=chunk.item_id,
            start=slot_start(solver.value(built.starts[i]), slot_min),
            end=slot_start(solver.value(built.starts[i]) + chunk.size, slot_min),
            id=chunk.block_id,
        )
        for i, chunk in enumerate(built.chunks)
    ]
    return SearchResult(blocks, "FEASIBLE" if shrink_status == "FEASIBLE" else status)


def _shrink(problem: Problem) -> tuple[Problem, list[int], str]:
    """Stage 1 of a partial search: the problem with each chunk cut to the length that fits, each start, and the status.

    Left-out chunks are dropped. Equal-length chunks of one item get their
    starts in index order, which the full model's symmetry breaking requires.
    """
    built = build_model(problem, partial=True)
    assert built is not None  # a partial model always exists
    solver, status = _run(built.model, problem.settings.work_limit, gap=0)
    slot_min = problem.settings.slot_min

    placed: list[tuple[Chunk, int]] = []
    for i, chunk in enumerate(built.chunks):
        size = solver.value(built.sizes[i])
        if size:
            item = problem.items[chunk.item_id]
            resized = replace(chunk, size=size, candidates=start_candidates(item, size, slot_min))
            placed.append((resized, solver.value(built.starts[i])))
    groups: dict[tuple[UUID, int], list[int]] = defaultdict(list)
    for k, (chunk, _) in enumerate(placed):
        groups[(chunk.item_id, chunk.size)].append(k)
    starts = [start for _, start in placed]
    for members in groups.values():
        for k, start in zip(members, sorted(starts[k] for k in members)):
            starts[k] = start
    return replace(problem, chunks=[chunk for chunk, _ in placed]), starts, status


def _run(model: cp_model.CpModel, work_limit: float, gap: int) -> tuple[cp_model.CpSolver, str]:
    """Solve deterministically (one worker, fixed seed, work limit); return the solver and its status name.

    Raises RuntimeError when it stops with no arrangement and no proof that none exists.
    """
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = work_limit
    solver.parameters.absolute_gap_limit = gap
    solver.parameters.num_workers = 1  # deterministic: same week, same schedule
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.INFEASIBLE):
        raise RuntimeError(
            f"CP-SAT found no arrangement within work_limit {work_limit} (status {solver.status_name(status)})"
        )
    return solver, solver.status_name(status)


def build_model(problem: Problem, partial: bool = False) -> BuiltModel | None:
    """Variables, hard constraints and score for a problem, or None if a chunk has nowhere to go.

    A partial model (stage 1 of a partial search) is never None, since a
    chunk with no room is left out of it, and its only score is the slots
    left unplaced.
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
    for block in problem.pinned:
        interval = (floor_slot(block.start, slot_min), ceil_slot(block.end, slot_min))
        busy.append(interval)
        kept_by_item[block.item_id].append(interval)
        if session_min(block) > 0:
            kept_days[block.item_id].add(local_day(interval[0]))

    dependents: dict[UUID, list[UUID]] = defaultdict(list)
    for item in items.values():
        for dep in item.depends_on:
            dependents[dep].append(item.id)

    def allowed(chunk: Chunk, start: int, size: int | None = None) -> bool:
        """Checks against fixed things only: kept blocks and their days."""
        end = start + (chunk.size if size is None else size)
        item = items[chunk.item_id]
        if any(a < end and start < b for a, b in busy):
            return False
        if any(b > start for dep in item.depends_on for _, b in kept_by_item[dep]):
            return False
        if any(a < end for later in dependents[chunk.item_id] for a, _ in kept_by_item[later]):
            return False
        return not (item.one_block_per_day and local_day(start) in kept_days[chunk.item_id])

    def room(chunk: Chunk, start: int, cap: int) -> int:
        """Partial: the most slots, up to `cap`, the chunk can hold from `start` around kept blocks."""
        if not allowed(chunk, start, 1):
            return 0
        end = start + cap
        for a, _ in busy:
            if start < a < end:
                end = a
        for later in dependents[chunk.item_id]:
            for a, _ in kept_by_item[later]:
                end = min(end, max(a, start))
        return end - start

    # Start slots per chunk. A partial model also knows the most slots each start can hold.
    domains: list[list[int]] = []
    caps: list[dict[int, int]] = []
    if partial:
        for chunk in chunks:
            fit = shrink_caps(items[chunk.item_id], chunk.size, slot_min)
            smallest = chunk.size if items[chunk.item_id].keep_length else 1
            caps.append({s: r for s, cap in fit.items() if (r := room(chunk, s, cap)) >= smallest})
        chunks = [chunk for chunk, cap in zip(chunks, caps) if cap]
        caps = [cap for cap in caps if cap]
        domains = [list(cap) for cap in caps]
    else:
        for chunk in chunks:
            values = [s for s in chunk.candidates if allowed(chunk, s)]
            if not values:
                return None
            domains.append(values)

    model = cp_model.CpModel()
    starts: list[cp_model.IntVar] = []
    sizes: list[cp_model.IntVar] = []  # partial only
    present: list[cp_model.IntVar] = []  # partial only
    intervals: list[cp_model.IntervalVar] = []
    day_vars: list[dict[date, cp_model.IntVar]] = []
    loads: list[dict[date, cp_model.LinearExprT]] = []  # slots each chunk puts on each day

    for i, chunk in enumerate(chunks):
        values = domains[i]
        start = model.new_int_var_from_domain(cp_model.Domain.from_values(values), f"start_{i}")
        starts.append(start)
        if partial:
            # Don't shorten sessions: the size is all or nothing.
            whole = [0, chunk.size] if items[chunk.item_id].keep_length else list(range(chunk.size + 1))
            size = model.new_int_var_from_domain(cp_model.Domain.from_values(whole), f"size_{i}")
            cap = model.new_int_var(1, chunk.size, f"cap_{i}")
            model.add_allowed_assignments([start, cap], list(caps[i].items()))
            model.add(size <= cap)
            is_present = model.new_bool_var(f"present_{i}")
            model.add(size >= 1).only_enforce_if(is_present)
            model.add(size == 0).only_enforce_if(~is_present)
            sizes.append(size)
            present.append(is_present)
            end = model.new_int_var(min(values), max(values) + chunk.size, f"end_{i}")
            intervals.append(model.new_optional_interval_var(start, size, end, is_present, f"block_{i}"))
        else:
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
        day_load: dict[date, cp_model.LinearExprT] = {}
        if partial:
            model.add(sum(days.values()) == present[i])  # a left-out chunk is on no day
            for day, on_day in days.items():
                on_day_size = model.new_int_var(0, chunk.size, f"chunk_{i}_size_on_{day}")
                model.add(on_day_size <= chunk.size * on_day)
                day_load[day] = on_day_size
            model.add(sum(day_load.values()) == sizes[i])
        else:
            model.add_exactly_one(days.values())
            day_load = {day: chunk.size * on_day for day, on_day in days.items()}
        day_vars.append(days)
        loads.append(day_load)

    model.add_no_overlap(intervals)

    def length(j: int) -> cp_model.LinearExprT:
        return sizes[j] if partial else chunks[j].size

    def when_present(*indexes: int) -> list[cp_model.IntVar]:
        """Enforcement literals: a constraint between chunks holds only if all of them are placed."""
        return [present[k] for k in indexes] if partial else []

    chunks_of: dict[UUID, list[int]] = defaultdict(list)
    for i, chunk in enumerate(chunks):
        chunks_of[chunk.item_id].append(i)

    for item_id, mine in chunks_of.items():
        item = items[item_id]
        # Dependencies between chunks: start after every chunk of each dependency ends.
        for dep in item.depends_on:
            for i in mine:
                for j in chunks_of.get(dep, []):
                    model.add(starts[i] >= starts[j] + length(j)).only_enforce_if(when_present(i, j))
        # Symmetry breaking: equal-size chunks of one item start in index order
        # (and in a partial model, an earlier one is placed if a later one is).
        for i, j in zip(mine, mine[1:]):
            if chunks[i].size == chunks[j].size:
                model.add(starts[i] < starts[j]).only_enforce_if(when_present(i, j))
                if partial:
                    model.add_implication(present[j], present[i])
        if item.one_block_per_day:
            for day in {d for i in mine for d in day_vars[i]}:
                model.add_at_most_one(day_vars[i][day] for i in mine if day in day_vars[i])

    # Daily limits: placed minutes on a day fit in what kept blocks leave free.
    # If kept blocks alone are over, nothing more goes there (not infeasible).
    kept_min = kept_minutes_by_day(problem.pinned, settings.timezone)
    for day in {d for vars_ in day_vars for d in vars_}:
        limit = day_limit_min(problem.daily_limits, day)
        if limit is not None:
            placed = sum(load[day] for load in loads if day in load)
            model.add(slot_min * placed <= max(0, limit - kept_min[day]))

    if partial:
        # Fewest slots left out, and on a tie, fewest current blocks moved or cut,
        # so new work never pushes out work that already has its place. Weighting
        # unplaced slots by (blocks that could move + 1) keeps them first.
        moved = []
        for i, chunk in enumerate(chunks):
            if chunk.previous_start is None:
                continue
            model.add_hint(starts[i], chunk.previous_start)
            model.add_hint(sizes[i], chunk.size)
            stays = model.new_bool_var(f"stays_{i}")
            model.add(starts[i] == chunk.previous_start).only_enforce_if(stays)
            model.add(sizes[i] == chunk.size).only_enforce_if(stays)
            moved.append(1 - stays)
        unplaced = sum(chunk.size - size for chunk, size in zip(chunks, sizes))
        model.minimize((len(moved) + 1) * unplaced + sum(moved))
        return BuiltModel(model, starts, 0, chunks, sizes)
    slack = _add_score(model, problem, starts, day_vars, chunks_of, busy, local_day)
    return BuiltModel(model, starts, slack, chunks)


def _add_score(
    model: cp_model.CpModel,
    problem: Problem,
    starts: list[cp_model.IntVar],
    day_vars: list[dict[date, cp_model.IntVar]],
    chunks_of: dict[UUID, list[int]],
    busy: list[Interval],
    local_day: Callable[[int], date],
) -> int:
    """Add the six score terms, minimize them in priority order, and return the slack in slots."""
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

    # 2. Spread: per item and day, new blocks beyond the first. A day that already
    #    has a kept block of the item makes every new block there an extra; the
    #    kept blocks' own extras are a constant, so they're left out. That keeps
    #    `extra` within 0..len(on_day), which the tier weights assume.
    kept_count: dict[tuple[UUID, date], int] = defaultdict(int)
    for block in problem.pinned:
        kept_count[(block.item_id, block.start.astimezone(zone).date())] += 1
    extras = []
    for item_id, mine in chunks_of.items():
        if problem.items[item_id].one_block_per_day:
            continue  # already at most one per day
        for day in {d for i in mine for d in day_vars[i]}:
            on_day = [day_vars[i][day] for i in mine if day in day_vars[i]]
            free = 0 if kept_count[(item_id, day)] else 1  # new blocks allowed before one is extra
            if len(on_day) <= free:
                continue
            extra = model.new_int_var(0, len(on_day), f"extra_{item_id}_{day}")
            model.add(extra >= sum(on_day) - free)
            extras.append(extra)

    # 3. Preferences: weighted soft constraints.
    times, max_times = _time_preference_penalties(model, problem, starts)
    rests, max_rests = _rest_penalties(model, problem, day_vars, chunks_of)
    preferences, max_preferences = times + rests, max_times + max_rests

    # 4. Earlier week: a chunk on day d costs its size times d's week number,
    #    counted from the Monday of the earliest day any chunk could start on.
    #    Linear in the day booleans, like spread and balance.
    later, max_later = _later_week_penalty(chunks, day_vars)

    # 5. Balance: the fullest day, in thousandths of that day's work-frame minutes.
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

    # 6. Earlier in the frame: slots from the start of the work-frame occurrence
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

    # Only blocks with a choice of start can come out later than optimal.
    flexible = sum(1 for chunk in chunks if len(chunk.candidates) > 1)
    slack = flexible * problem.settings.earliness_slack_min // slot_min
    w_offset, w_balance, w_later, w_preferences, w_spread, w_stability = tier_weights(
        [max_offset_total, max_fullest, max_later, max_preferences, len(chunks), len(moved)], slack
    )
    model.minimize(
        w_stability * sum(moved)
        + w_spread * sum(extras)
        + w_preferences * preferences
        + w_later * later
        + w_balance * fullest
        + w_offset * sum(offsets)
    )
    return slack


def tier_weights(max_totals: list[int], slack: int) -> list[int]:
    """Weights for score tiers given lowest first, with each tier's largest possible total.

    The lowest tier gets weight 1. Every other tier's weight is the most all
    lower tiers can add up to, plus `slack`, plus one. So being 1 worse in a
    tier costs more than any gain below it plus the slack, and a plan within
    `slack` of the best can only differ in the lowest tier.
    """
    weights: list[int] = []
    lower_total = 0
    for max_total in max_totals:
        weight = lower_total + slack + 1 if weights else 1
        weights.append(weight)
        lower_total += weight * max_total
    return weights


def _time_preference_penalties(
    model: cp_model.CpModel, problem: Problem, starts: list[cp_model.IntVar]
) -> tuple[cp_model.LinearExprT, int]:
    """Sum of each chunk's preference penalty, and the most it can add up to.

    A chunk's penalty depends only on its start, so like the offsets it is a
    table of (start, penalty) pairs worked out ahead of time.
    """
    slot_min = problem.settings.slot_min
    inside = [
        {t for a, b in _spans(list(pref.windows), slot_min) for t in range(a, b)}
        for pref in problem.preferences
    ]
    penalties: list[cp_model.IntVar] = []
    bound = 0
    for i, chunk in enumerate(problem.chunks):
        item = problem.items[chunk.item_id]
        mine = [(p, inside[k]) for k, p in enumerate(problem.preferences) if p.target.matches(item)]
        if not mine:
            continue
        pairs = [(s, _preference_cost(s, chunk.size, mine)) for s in chunk.candidates]
        top = max(cost for _, cost in pairs)
        if top == 0:
            continue
        penalty = model.new_int_var(0, top, f"preference_{i}")
        model.add_allowed_assignments([starts[i], penalty], pairs)
        penalties.append(penalty)
        bound += top
    return sum(penalties), bound


def _later_week_penalty(
    chunks: list[Chunk], day_vars: list[dict[date, cp_model.IntVar]]
) -> tuple[cp_model.LinearExprT, int]:
    """Sum of size * week number over chunks' start days, and the most it can add up to."""
    all_days = [day for vars_ in day_vars for day in vars_]
    if not all_days:
        return 0, 0
    first = min(all_days)
    monday = first - timedelta(days=first.weekday())
    terms: list[cp_model.LinearExprT] = []
    bound = 0
    for chunk, vars_ in zip(chunks, day_vars):
        costs = {day: (day - monday).days // 7 * chunk.size for day in vars_}
        terms += [cost * vars_[day] for day, cost in costs.items() if cost]
        bound += max(costs.values(), default=0)
    return sum(terms), bound


def _rest_penalties(
    model: cp_model.CpModel,
    problem: Problem,
    day_vars: list[dict[date, cp_model.IntVar]],
    chunks_of: dict[UUID, list[int]],
) -> tuple[cp_model.LinearExprT, int]:
    """Weighted cost of session pairs that sit too few days apart.

    One boolean per pair of sessions. For every pair of days that would be too
    close, "chunk i on day d and chunk j on day e" implies the boolean, written
    as the clause (not d) or (not e) or too_close. Minimizing keeps the boolean
    false unless some close pair really happens. A kept session is a fixed day.
    """
    zone = ZoneInfo(problem.settings.timezone)
    slot_min = problem.settings.slot_min
    terms: list[cp_model.LinearExprT] = []
    bound = 0
    for r, rest in enumerate(problem.rests):
        for item_id, mine in chunks_of.items():
            if not rest.target.matches(problem.items[item_id]):
                continue
            kept = [
                (b.start.astimezone(zone).date(), max(1, session_min(b) // slot_min))
                for b in problem.pinned
                if b.item_id == item_id and session_min(b) > 0
            ]
            for a, i in enumerate(mine):
                size_i = problem.chunks[i].size
                others = [(day_vars[j], problem.chunks[j].size) for j in mine[a + 1 :]]
                others += [({day: None}, size) for day, size in kept]
                for days_j, size_j in others:
                    close = [
                        (d, e)
                        for d in day_vars[i]
                        for e in days_j
                        if abs((d - e).days) <= rest.min_gap_days
                    ]
                    if not close:
                        continue
                    too_close = model.new_bool_var(f"rest_{r}_{i}_{len(terms)}")
                    for d, e in close:
                        literals = [~day_vars[i][d], too_close]
                        if days_j[e] is not None:
                            literals.append(~days_j[e])
                        model.add_bool_or(literals)
                    cost = rest.weight * min(size_i, size_j)
                    terms.append(cost * too_close)
                    bound += cost
    return sum(terms), bound


def _preference_cost(start: int, size: int, prefs: list[tuple[TimePreference, set[int]]]) -> int:
    """Weighted slots of [start, start + size) on the wrong side of each preference."""
    cost = 0
    for pref, inside in prefs:
        hits = sum(1 for t in range(start, start + size) if t in inside)
        cost += pref.weight * (hits if pref.avoid else size - hits)
    return cost


def _spans(windows: list[Window], slot_min: int) -> list[Interval]:
    """Each window as (first start slot, end slot), sorted by start."""
    return sorted((ceil_slot(w.start, slot_min), floor_slot(w.end, slot_min)) for w in windows)


def _anchor_of(slot: int, frames: list[Interval], own: list[Interval]) -> int:
    """First slot of the earliest frame occurrence holding `slot`, else of its item window."""
    for a, b in frames + own:
        if a <= slot < b:
            return a
    return slot
