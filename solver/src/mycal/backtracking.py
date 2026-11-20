"""Hand-written backtracking engine.

Each chunk is a variable whose domain is its candidate start slots. Chunks are
assigned one at a time, most constrained first; every placement is checked
against the hard constraints, and the search backs up when a chunk has no
start left. It returns the first valid arrangement and ignores soft
constraints, apart from trying each block's previous start first.

Partial placement is greedy, with no backing up: chunks with a current block
first, then in the same order, each chunk takes the start that holds the most
of it (its previous start, then the earliest, on a tie), shrinking from the
end, or is left out. That is a
best effort; finding the plan that leaves out the least would take a full
branch-and-bound search.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from functools import cache
from uuid import UUID
from zoneinfo import ZoneInfo

from mycal.model import Block
from mycal.problem import (
    Chunk,
    Problem,
    SearchResult,
    ceil_slot,
    day_limit_min,
    floor_slot,
    kept_minutes_by_day,
    session_min,
    shrink_caps,
    slot_start,
)

Interval = tuple[int, int]


def search(problem: Problem, partial: bool = False) -> SearchResult:
    """Return new blocks for every chunk (FOUND), or no blocks if no arrangement fits (INFEASIBLE).

    With `partial`, return the greedy partial plan (PARTIAL) instead.
    """
    chunks = problem.chunks
    items = problem.items
    slot_min = problem.settings.slot_min
    zone = ZoneInfo(problem.settings.timezone)

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

    kept_min = kept_minutes_by_day(problem.pinned, problem.settings.timezone)
    placed: dict[int, int] = {}  # chunk index -> start slot
    shrunk: dict[int, int] = {}  # chunk index -> slots, for chunks placed shorter (partial only)

    def size_of(j: int) -> int:
        return shrunk.get(j, chunks[j].size)

    def intervals_of(item_id: UUID) -> list[Interval]:
        own = [(s, s + size_of(j)) for j, s in placed.items() if chunks[j].item_id == item_id]
        return kept_by_item[item_id] + own

    def fits(i: int, start: int, size: int | None = None) -> bool:
        """Whether chunk i fits at `start`, at full size or (partial only) at `size` slots."""
        chunk = chunks[i]
        size = chunk.size if size is None else size
        end = start + size
        item = items[chunk.item_id]

        # No overlap with kept blocks or blocks placed so far.
        if any(a < end and start < b for a, b in busy):
            return False
        for j, s in placed.items():
            if s < end and start < s + size_of(j):
                return False

        # Symmetry breaking: equal-size chunks of one item start in index order,
        # so the search never retries the same layout with chunks swapped.
        # The greedy partial pass never retries, so it skips this.
        for j, s in placed.items():
            other = chunks[j]
            if not partial and other.item_id == chunk.item_id and other.size == chunk.size and (j < i) != (s < start):
                return False

        # Dependencies, checked both ways since chunks are placed in any order.
        for dep in item.depends_on:
            if any(b > start for _, b in intervals_of(dep)):
                return False
        for later in dependents[chunk.item_id]:
            if any(a < end for a, _ in intervals_of(later)):
                return False

        if item.one_block_per_day:
            day = local_day(start)
            if day in kept_days[chunk.item_id]:
                return False
            for j, s in placed.items():
                if chunks[j].item_id == chunk.item_id and local_day(s) == day:
                    return False

        # Daily limits: everything on this local day, including this block.
        day = local_day(start)
        limit = day_limit_min(problem.daily_limits, day)
        if limit is not None:
            placed_slots = sum(size_of(j) for j, s in placed.items() if local_day(s) == day)
            if kept_min[day] + (placed_slots + size) * slot_min > limit:
                return False

        return True

    def deadline_key(chunk: Chunk) -> tuple[bool, float]:
        deadline = items[chunk.item_id].deadline
        return (deadline is None, deadline.timestamp() if deadline else 0.0)

    # Most constrained chunk first: fewest candidates, then earliest deadline.
    order = sorted(range(len(chunks)), key=lambda i: (len(chunks[i].candidates), deadline_key(chunks[i])))

    def assign(k: int) -> bool:
        if k == len(order):
            return True
        i = order[k]
        for start in _value_order(chunks[i], chunks[i].candidates):
            if fits(i, start):
                placed[i] = start
                if assign(k + 1):
                    return True
                del placed[i]
        return False

    def place_greedily() -> None:
        # Current blocks first, so new work never pushes out work that already has its place.
        # Then sessions that can't be shortened, since they need a whole gap.
        def rank(i: int) -> tuple[bool, bool]:
            return chunks[i].previous_start is None, not items[chunks[i].item_id].keep_length

        for i in sorted(order, key=rank):
            chunk = chunks[i]
            caps = shrink_caps(items[chunk.item_id], chunk.size, slot_min)
            smallest = chunk.size if items[chunk.item_id].keep_length else 1
            best: tuple[int, int] | None = None  # (start, size)
            for start in _value_order(chunk, tuple(caps)):
                for size in range(caps[start], max(best[1] if best else 0, smallest - 1), -1):
                    if fits(i, start, size):
                        best = (start, size)
                        break
                if best and best[1] == chunk.size:
                    break
            if best:
                placed[i] = best[0]
                if best[1] < chunk.size:
                    shrunk[i] = best[1]

    if partial:
        place_greedily()
        status = "PARTIAL"
    elif assign(0):
        status = "FOUND"
    else:
        return SearchResult(None, "INFEASIBLE")

    blocks = [
        Block(
            item_id=chunks[i].item_id,
            start=slot_start(s, slot_min),
            end=slot_start(s + size_of(i), slot_min),
            id=chunks[i].block_id,
        )
        for i, s in placed.items()
    ]
    return SearchResult(blocks, status)


def _value_order(chunk: Chunk, starts: tuple[int, ...]) -> Iterator[int]:
    """Previous start first (stability), then earliest first."""
    if chunk.previous_start in starts:
        yield chunk.previous_start
    for start in starts:
        if start != chunk.previous_start:
            yield start
