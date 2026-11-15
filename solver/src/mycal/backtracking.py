"""Hand-written backtracking engine.

Each chunk is a variable whose domain is its candidate start slots. Chunks are
assigned one at a time, most constrained first; every placement is checked
against the hard constraints, and the search backs up when a chunk has no
start left. It returns the first valid arrangement and ignores soft
constraints, apart from trying each block's previous start first.
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
    covered_min,
    day_limit_min,
    floor_slot,
    kept_minutes_by_day,
    slot_start,
)

Interval = tuple[int, int]


def search(problem: Problem) -> SearchResult:
    """Return new blocks for every chunk (FOUND), or no blocks if no arrangement fits (INFEASIBLE)."""
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
        if covered_min(block) > 0:
            kept_days[block.item_id].add(local_day(interval[0]))

    dependents: dict[UUID, list[UUID]] = defaultdict(list)
    for item in items.values():
        for dep in item.depends_on:
            dependents[dep].append(item.id)

    kept_min = kept_minutes_by_day(problem.pinned, problem.settings.timezone)
    placed: dict[int, int] = {}  # chunk index -> start slot

    def intervals_of(item_id: UUID) -> list[Interval]:
        own = [(s, s + chunks[j].size) for j, s in placed.items() if chunks[j].item_id == item_id]
        return kept_by_item[item_id] + own

    def fits(i: int, start: int) -> bool:
        chunk = chunks[i]
        end = start + chunk.size
        item = items[chunk.item_id]

        # No overlap with kept blocks or blocks placed so far.
        if any(a < end and start < b for a, b in busy):
            return False
        for j, s in placed.items():
            if s < start + chunk.size and start < s + chunks[j].size:
                return False

        # Symmetry breaking: equal-size chunks of one item start in index order,
        # so the search never retries the same layout with chunks swapped.
        for j, s in placed.items():
            other = chunks[j]
            if other.item_id == chunk.item_id and other.size == chunk.size and (j < i) != (s < start):
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
            placed_slots = sum(chunks[j].size for j, s in placed.items() if local_day(s) == day)
            if kept_min[day] + (placed_slots + chunk.size) * slot_min > limit:
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
        for start in _value_order(chunks[i]):
            if fits(i, start):
                placed[i] = start
                if assign(k + 1):
                    return True
                del placed[i]
        return False

    if not assign(0):
        return SearchResult(None, "INFEASIBLE")

    blocks = [
        Block(
            item_id=chunks[i].item_id,
            start=slot_start(s, slot_min),
            end=slot_start(s + chunks[i].size, slot_min),
            id=chunks[i].block_id,
        )
        for i, s in placed.items()
    ]
    return SearchResult(blocks, "FOUND")


def _value_order(chunk: Chunk) -> Iterator[int]:
    """Previous start first (stability), then earliest first."""
    if chunk.previous_start in chunk.candidates:
        yield chunk.previous_start
    for start in chunk.candidates:
        if start != chunk.previous_start:
            yield start
