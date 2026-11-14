"""Turn solve() inputs into a slot-based problem that every engine searches.

Time is a grid of slots of `slot_min` minutes, numbered from the Unix epoch
in UTC. Each Chunk is one block still to be placed; its candidates are the
start slots where it fits entirely inside one of its item's windows and ends
by the item's deadline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from mycal.model import Block, BlockStatus, Constraint, Item
from mycal.settings import SolverSettings

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One piece of an item's remaining work, to become one block."""

    item_id: UUID
    block_id: UUID
    size: int
    candidates: tuple[int, ...]
    previous_start: int | None = None


@dataclass(slots=True)
class Problem:
    settings: SolverSettings
    items: dict[UUID, Item]
    kept: list[Block]
    chunks: list[Chunk]


def floor_slot(moment: datetime, slot_min: int) -> int:
    return (moment - EPOCH) // timedelta(minutes=slot_min)


def ceil_slot(moment: datetime, slot_min: int) -> int:
    return -((EPOCH - moment) // timedelta(minutes=slot_min))


def slot_start(slot: int, slot_min: int) -> datetime:
    return EPOCH + slot * timedelta(minutes=slot_min)


def is_kept(block: Block) -> bool:
    """Locked blocks and completion history are kept; unlocked planned blocks get re-placed."""
    return block.locked or block.status is not BlockStatus.PLANNED


def covered_min(block: Block) -> int:
    """Minutes of an item's work this kept block already accounts for."""
    length = int((block.end - block.start) / timedelta(minutes=1))
    if block.status in (BlockStatus.DONE, BlockStatus.PARTIAL):
        return block.actual_min if block.actual_min is not None else length
    if block.locked and block.status is BlockStatus.PLANNED:
        return length
    return 0


def build_problem(
    items: list[Item],
    blocks: list[Block],
    constraints: list[Constraint],
    settings: SolverSettings,
) -> Problem:
    """Work out the kept blocks and the chunks still to place.

    Raises ValueError for a hard constraint kind no engine supports yet, so a
    rule is never silently dropped, and for an item with no estimate and more
    than one window.
    """
    for constraint in constraints:
        if constraint.hard:
            raise ValueError(f"Hard constraint kind {constraint.kind!r} is not supported yet")

    kept = [b for b in blocks if is_kept(b)]
    replaced = sorted((b for b in blocks if not is_kept(b)), key=lambda b: b.start)

    chunks: list[Chunk] = []
    for item in items:
        item_kept = [b for b in kept if b.item_id == item.id]
        item_old = [b for b in replaced if b.item_id == item.id]
        chunks.extend(_item_chunks(item, item_kept, item_old, settings.slot_min))

    return Problem(settings, {item.id: item for item in items}, kept, chunks)


def _item_chunks(item: Item, kept: list[Block], old: list[Block], slot_min: int) -> list[Chunk]:
    """Chunks for one item. Old unlocked blocks pass their id and start to chunk i."""
    if not item.windows:
        return []  # not scheduled yet; stays in the task list

    if item.estimate_min is None:
        sizes = _fill_window_size(item, kept, slot_min)
    else:
        remaining = item.estimate_min - sum(covered_min(b) for b in kept)
        if remaining <= 0:
            return []
        total_slots = -(-remaining // slot_min)
        sizes = split_slots(total_slots, item.max_chunk_min, slot_min)

    chunks = []
    for i, size in enumerate(sizes):
        previous = old[i] if i < len(old) else None
        chunks.append(
            Chunk(
                item_id=item.id,
                block_id=previous.id if previous else uuid4(),
                size=size,
                candidates=_candidates(item, size, slot_min),
                previous_start=ceil_slot(previous.start, slot_min) if previous else None,
            )
        )
    return chunks


def _fill_window_size(item: Item, kept: list[Block], slot_min: int) -> list[int]:
    """An item without an estimate gets one block filling its single window exactly."""
    if len(item.windows) > 1:
        raise ValueError(
            f"Item {item.title!r} has no estimate_min but {len(item.windows)} windows; "
            "set an estimate"
        )
    if kept:
        return []
    window = item.windows[0]
    size = floor_slot(window.end, slot_min) - ceil_slot(window.start, slot_min)
    return [max(size, 1)]  # a window smaller than one slot yields no candidates


def split_slots(total: int, max_chunk_min: int | None, slot_min: int) -> list[int]:
    """Split `total` slots into the fewest near-equal chunks no longer than max_chunk_min.

    5h with a 2h max at 15-minute slots is 20 slots in 3 chunks: 7 + 7 + 6.
    """
    if max_chunk_min is None:
        return [total]
    max_slots = max(1, max_chunk_min // slot_min)
    count = -(-total // max_slots)
    base, extra = divmod(total, count)
    return [base + 1] * extra + [base] * (count - extra)


def _candidates(item: Item, size: int, slot_min: int) -> tuple[int, ...]:
    """Start slots where a block of `size` slots fits in a window and ends by the deadline.

    Window edges that are not on the slot grid are rounded inward.
    """
    latest_end = floor_slot(item.deadline, slot_min) if item.deadline else None
    starts: set[int] = set()
    for window in item.windows:
        first = ceil_slot(window.start, slot_min)
        end = floor_slot(window.end, slot_min)
        if latest_end is not None:
            end = min(end, latest_end)
        starts.update(range(first, end - size + 1))
    return tuple(sorted(starts))
