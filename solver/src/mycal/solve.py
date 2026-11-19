"""The solver interface. The backtracking and CP-SAT engines both sit behind solve()."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import timedelta
from uuid import UUID

from mycal import backtracking, cp_sat
from mycal.model import Block, Constraint, Item, WorkFrame
from mycal.problem import Problem, SearchResult, build_problem, pinned_overlaps, work_left_min
from mycal.settings import Engine, SolverSettings

ENGINES: dict[Engine, Callable[[Problem, bool], SearchResult]] = {
    "backtracking": backtracking.search,
    "cp_sat": cp_sat.search,
}


@dataclass(frozen=True, slots=True)
class Unplaced:
    """Work of one item that didn't fit: `minutes` of its remaining work have no block."""

    item_id: UUID
    minutes: int


@dataclass(slots=True)
class SolveResult:
    """`blocks` is the full arrangement: kept blocks unchanged, fixed events at their real times and placed blocks, by start.

    `feasible` is True when all remaining work was placed. When it wasn't,
    `unplaced` lists what is missing per item, and `blocks` holds the best
    partial plan (or nothing, if solve() was called with partial=False).

    `status` says how the search ended: OPTIMAL, FEASIBLE (CP-SAT stopped at its
    time limit with a valid but unproven arrangement) or INFEASIBLE, and FOUND
    for backtracking, which does not score, or PARTIAL for its best-effort
    partial plan.

    `overlaps` lists block id pairs (earlier first) where a fixed event's real
    times overlap another fixed event or a kept block. Double booking is
    allowed and only reported, so the caller can show it.
    """

    feasible: bool
    blocks: list[Block] = field(default_factory=list)
    status: str = ""
    overlaps: list[tuple[UUID, UUID]] = field(default_factory=list)
    unplaced: list[Unplaced] = field(default_factory=list)


def solve(
    items: list[Item],
    blocks: list[Block],
    work_frames: list[WorkFrame],
    constraints: list[Constraint],
    settings: SolverSettings,
    partial: bool = True,
) -> SolveResult:
    """Place blocks for the given items and return the arrangement.

    This is a pure function: no database, HTTP, file I/O or UI, and the inputs
    are not mutated. Times are UTC throughout.

    Inputs:
        items: what needs scheduling. The solver reads `Item.windows` only,
            never `flex_preset` or `preset_params`. An item with no windows is
            skipped. An item with no estimate is a fixed event: one block at
            its single window's real times, never moved or rounded to the
            slot grid.
        blocks: existing blocks. Locked blocks and completion history (any
            status other than planned) are kept and returned unchanged.
            Unlocked planned blocks are the current plan: they are replaced,
            and their ids and starts carry over where possible.
        work_frames: repeating frames. Already folded into windows, so they
            never decide placement; CP-SAT uses them only to measure how full
            each day is.
        constraints: extra rules. Supported: hard "daily_limit" (params
            max_min, optional weekdays) and soft "time_preference" (params
            windows in UTC, mode "prefer" or "avoid", optional item_ids and
            series_ids; compile local times first with compile_constraint)
            and soft "rest_between" (params min_gap_days, default 1, and the
            same optional targets).
            Soft kinds only change the CP-SAT score; backtracking ignores
            them. A soft daily_limit, a hard soft-only kind or any other hard
            kind raises ValueError; other soft kinds are ignored for now.
        settings: slot size, home timezone and engine.
        partial: when the work doesn't all fit, return the best partial plan
            (True) or no plan (False).

    Hard constraints:
        - every block lies inside one of its item's windows
        - no two blocks overlap, and nothing overlaps a kept block
        - other work stays off every slot a kept block or fixed event
          touches (9:10 to 10:00 blocks 9:00 to 10:00)
        - fixed events may overlap each other and kept blocks (double
          booking); each overlap is reported in `overlaps`, never refused
        - all blocks of an item end by its deadline
        - an item starts after every item in `depends_on` has ended
        - with `one_block_per_day`, no two of an item's blocks share a local day
        - daily limits: minutes on a limited local day stay within the limit
          (if kept blocks alone exceed it, nothing more is placed that day)

    Partial placement: when not all remaining work fits, a second search
    places as much as it can within the same hard constraints. Blocks can be
    left out or shortened (they keep their start and lose slots from the end),
    and `unplaced` lists the minutes that have no block. CP-SAT leaves out as
    few slots as it can find within the work limit; backtracking is a greedy
    best effort and may leave out more. A plan that fits never goes through
    this second search, so it comes out the same as without partial placement.

    Returns:
        SolveResult with `feasible=True` and the arrangement when all work
        fits. Otherwise `feasible=False`, the partial arrangement and
        `unplaced`, or no blocks with partial=False.
    """
    problem = build_problem(items, blocks, constraints, settings, work_frames)
    engine = ENGINES[settings.engine]
    found = engine(problem, False)
    if found.blocks is None:
        if not partial:
            return SolveResult(feasible=False, status=found.status, unplaced=_unplaced(problem, []))
        found = engine(problem, True)
    assert found.blocks is not None  # a partial search always returns a plan
    unplaced = _unplaced(problem, found.blocks)
    arrangement = [replace(b) for b in problem.kept] + problem.fixed + found.blocks
    return SolveResult(
        feasible=not unplaced,
        blocks=sorted(arrangement, key=lambda b: b.start),
        status=found.status,
        overlaps=pinned_overlaps(problem),
        unplaced=unplaced,
    )


def _unplaced(problem: Problem, placed: list[Block]) -> list[Unplaced]:
    """Per item, in chunk order: the minutes of its chunks that `placed` doesn't hold.

    Chunks are whole slots, so the count is capped at the item's real
    remaining work (50 minutes on a 15-minute grid is 4 slots, but 50 minutes).
    """
    slot_min = problem.settings.slot_min
    wanted: dict[UUID, int] = defaultdict(int)
    for chunk in problem.chunks:
        wanted[chunk.item_id] += chunk.size
    for block in placed:
        wanted[block.item_id] -= (block.end - block.start) // timedelta(minutes=slot_min)
    return [
        Unplaced(item_id, min(missing * slot_min, work_left_min(problem.items[item_id], problem.kept)))
        for item_id, missing in wanted.items()
        if missing > 0
    ]
