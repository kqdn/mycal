"""The solver interface. The backtracking and CP-SAT engines both sit behind solve()."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from mycal import backtracking, cp_sat
from mycal.model import Block, Constraint, Item, WorkFrame
from mycal.problem import Problem, SearchResult, build_problem, fixed_clash
from mycal.settings import Engine, SolverSettings

ENGINES: dict[Engine, Callable[[Problem], SearchResult]] = {
    "backtracking": backtracking.search,
    "cp_sat": cp_sat.search,
}


@dataclass(slots=True)
class SolveResult:
    """`blocks` is the full arrangement: kept blocks unchanged, fixed events at their real times and placed blocks, by start.

    `status` says how the search ended: OPTIMAL, FEASIBLE (CP-SAT stopped at its
    time limit with a valid but unproven arrangement) or INFEASIBLE, and FOUND
    for backtracking, which does not score.
    """

    feasible: bool
    blocks: list[Block] = field(default_factory=list)
    status: str = ""


def solve(
    items: list[Item],
    blocks: list[Block],
    work_frames: list[WorkFrame],
    constraints: list[Constraint],
    settings: SolverSettings,
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

    Hard constraints:
        - every block lies inside one of its item's windows
        - no two blocks overlap, and nothing overlaps a kept block
        - other work stays off every slot a kept block or fixed event
          touches (9:10 to 10:00 blocks 9:00 to 10:00), but fixed events
          clash with each other and with kept blocks only on real times
        - all blocks of an item end by its deadline
        - an item starts after every item in `depends_on` has ended
        - with `one_block_per_day`, no two of an item's blocks share a local day
        - daily limits: minutes on a limited local day stay within the limit
          (if kept blocks alone exceed it, nothing more is placed that day)

    Returns:
        SolveResult with `feasible=True` and the arrangement, or
        `feasible=False` and no blocks when the hard constraints cannot all
        hold (a deadline is at risk).
    """
    problem = build_problem(items, blocks, constraints, settings, work_frames)
    if fixed_clash(problem):
        return SolveResult(feasible=False, status="INFEASIBLE")
    found = ENGINES[settings.engine](problem)
    if found.blocks is None:
        return SolveResult(feasible=False, status=found.status)
    arrangement = [replace(b) for b in problem.kept] + problem.fixed + found.blocks
    return SolveResult(feasible=True, blocks=sorted(arrangement, key=lambda b: b.start), status=found.status)
