"""The solver interface. The backtracking and CP-SAT solvers both sit behind solve()."""

from __future__ import annotations

from dataclasses import dataclass, field

from mycal.model import Block, Constraint, Item, WorkFrame


@dataclass(frozen=True, slots=True)
class SolverSettings:
    """Tunable settings. `slot_min` is the one place the slot size lives."""

    slot_min: int = 15


@dataclass(slots=True)
class SolveResult:
    """`blocks` is the full arrangement: locked blocks unchanged plus placed ones."""

    feasible: bool
    blocks: list[Block] = field(default_factory=list)


def solve(
    items: list[Item],
    blocks: list[Block],
    work_frames: list[WorkFrame],
    constraints: list[Constraint],
    settings: SolverSettings = SolverSettings(),
) -> SolveResult:
    """Place blocks for the given items and return the arrangement.

    This is a pure function: no database, HTTP, file I/O or UI, and the inputs
    are not mutated. Times are UTC throughout.

    Inputs:
        items: what needs scheduling. The solver reads `Item.windows` only,
            never `flex_preset` or `preset_params`.
        blocks: existing blocks. Locked blocks are pinned and returned
            unchanged. Unlocked blocks are the current plan, used for stability.
        work_frames: repeating frames, the default source of windows.
        constraints: extra hard or weighted soft rules.
        settings: solver settings, including the slot size.

    Hard constraints:
        - every block lies inside one of its item's windows
        - no two blocks overlap, and nothing overlaps a locked block
        - all blocks of an item end by its deadline
        - an item starts after every item in `depends_on` has ended

    Returns:
        SolveResult with `feasible=True` and the placed blocks, or
        `feasible=False` and no blocks when no arrangement satisfies the hard
        constraints (a deadline is at risk).
    """
    raise NotImplementedError("solve() is not implemented yet")
