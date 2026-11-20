"""Check-ins and on-miss policies (Milestone 7).

Not part of the solver: a caller, like planner.py and store.py. It turns an
answer (Yes, Partly, No) into a block's new status and, for a missed part,
the on-miss policy that runs on it. The solver never sees a policy: the
block's missed_action sets how many minutes of work it still covers (see
covered_min), and that is how the plan changes.

Working out an answer (resolve, expire_all) reads the database but writes
nothing, so the API can try it on a copy first; apply writes it.

A checkable block that has ended and is still planned is waiting for a
check-in. Until it is answered it counts as done, like any past block. After
CHECK_IN_GRACE it becomes unanswered and counts as No. An unanswered block of
an Ask item keeps waiting (missed_action None) until it is answered.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from uuid import UUID
from zoneinfo import ZoneInfo

from mycal import store
from mycal.model import MISSABLE, Block, BlockStatus, FlexPreset, Item, OnMiss
from mycal.planner import open_from_moment
from mycal.recurrence import occurrence_dates, occurrence_on
from mycal.settings import SolverSettings

CHECK_IN_GRACE = timedelta(hours=4)
CATCH_UP_PREFIX = "Catch up: "
# A missed exact-time item is usually caught up from a recording, which takes longer.
RECORDING_FACTOR = 1.25
# A catch-up deadline closer than this leaves too little room, so the next choice is used.
MIN_CATCH_UP_LEAD = timedelta(days=1)
CATCH_UP_FALLBACK = timedelta(days=7)
# How far ahead to look for a series' next occurrence.
NEXT_OCCURRENCE_LOOKAHEAD = timedelta(days=366)


class Answer(Enum):
    YES = "yes"
    PARTLY = "partly"
    NO = "no"


class Refused(ValueError):
    """An answer that can't be recorded, with a sentence the page can show."""


class NeedsChoice(Refused):
    """An Ask item answered Partly or No without saying what to do with the missed part."""


@dataclass(slots=True)
class Resolution:
    """What answering does: the block's new state, a catch-up item to add, catch-up items to delete."""

    block: Block
    catch_up: Item | None = None
    drop: list[UUID] = field(default_factory=list)


# Which blocks wait for a check-in


def awaits_check_in(block: Block, item: Item, moment: datetime) -> bool:
    """A checkable block that has ended and has no answer yet."""
    return item.checkable and block.status is BlockStatus.PLANNED and block.end <= moment


def awaits_choice(block: Block) -> bool:
    """An unanswered (or missed) block of an Ask item: nothing moves until a choice is made."""
    return block.status in MISSABLE and block.missed_action is None


def pending(conn: sqlite3.Connection, moment: datetime) -> list[tuple[Block, Item]]:
    """Blocks to ask about, earliest end first: ended and unanswered, or waiting on an Ask choice."""
    items = {i.id: i for i in store.list_items(conn)}
    found = [
        (b, items[b.item_id])
        for b in store.list_blocks(conn)
        if awaits_check_in(b, items[b.item_id], moment) or awaits_choice(b)
    ]
    return sorted(found, key=lambda pair: (pair[0].end, str(pair[0].id)))


# Answering


def policy_for(item: Item, chosen: OnMiss | None = None) -> OnMiss:
    """The policy that runs on a missed part: the choice made, else the item's own.

    An exact-time item can't move, so Reschedule means Skip for it.
    """
    policy = chosen if chosen is not None else item.on_miss
    if policy is OnMiss.RESCHEDULE and item.flex_preset is FlexPreset.EXACT:
        return OnMiss.SKIP
    return policy


def resolve(
    conn: sqlite3.Connection,
    settings: SolverSettings,
    block: Block,
    item: Item,
    answer: Answer,
    moment: datetime,
    done_min: int | None = None,
    chosen: OnMiss | None = None,
) -> Resolution:
    """What answering a block does. Raises Refused (or NeedsChoice) with a sentence for the page.

    Answering again replaces the earlier answer: its catch-up item is dropped,
    unless one of that item's sessions has started or is finished.
    """
    if not item.checkable:
        raise Refused("This item doesn't take check-ins.")
    if block.start > moment:
        raise Refused("It hasn't started yet.")
    drop = _undo(conn, block, moment)
    length = _length(block)
    if answer is Answer.YES:
        done = replace(block, status=BlockStatus.DONE, actual_min=length, completed_at=moment, missed_action=None)
        return Resolution(done, drop=drop)

    policy = policy_for(item, chosen)
    if policy is OnMiss.ASK:
        raise NeedsChoice("Pick what happens to the time you missed.")
    if answer is Answer.PARTLY:
        if done_min is None or not 0 < done_min < length:
            raise Refused(f"Enter how much you got done, between 1m and {length - 1}m.")
        new = replace(block, status=BlockStatus.PARTIAL, actual_min=done_min, completed_at=moment, missed_action=policy)
    else:
        new = replace(block, status=BlockStatus.MISSED, actual_min=None, completed_at=None, missed_action=policy)
    missed = length - (done_min if answer is Answer.PARTLY and done_min else 0)
    catch_up = catch_up_item(conn, settings, block, item, missed, moment) if policy is OnMiss.CATCH_UP else None
    return Resolution(new, catch_up, drop)


def expire_all(conn: sqlite3.Connection, settings: SolverSettings, moment: datetime) -> list[Resolution]:
    """Check-ins left unanswered past CHECK_IN_GRACE: each counts as No, with its item's policy.

    An Ask item's block becomes unanswered with no policy yet, so it keeps waiting.
    """
    resolutions = []
    for block, item in pending(conn, moment):
        if block.status is not BlockStatus.PLANNED or block.end + CHECK_IN_GRACE > moment:
            continue
        policy = policy_for(item)
        action = None if policy is OnMiss.ASK else policy
        new = replace(block, status=BlockStatus.UNANSWERED, actual_min=None, completed_at=None, missed_action=action)
        catch_up = catch_up_item(conn, settings, block, item, _length(block), moment) if action is OnMiss.CATCH_UP else None
        resolutions.append(Resolution(new, catch_up))
    return resolutions


def waiting(resolution: Resolution) -> Resolution:
    """The same answer with nothing run on the missed part yet, for when its policy can't fit."""
    if resolution.block.status not in MISSABLE:
        return resolution
    return Resolution(replace(resolution.block, missed_action=None), None, resolution.drop)


def apply(conn: sqlite3.Connection, resolutions: list[Resolution]) -> None:
    """Write answers: delete dropped catch-up items, add new ones, then store the blocks."""
    for resolution in resolutions:
        for item_id in resolution.drop:
            store.delete_item(conn, item_id)
        if resolution.catch_up is not None:
            store.put_item(conn, resolution.catch_up)
    store.put_blocks(conn, [r.block for r in resolutions])


def _undo(conn: sqlite3.Connection, block: Block, moment: datetime) -> list[UUID]:
    """The catch-up items made for an earlier answer, which a new answer drops. Refused if one has begun."""
    if block.missed_action is not OnMiss.CATCH_UP:
        return []
    made = [i for i in store.list_items(conn) if i.catch_up_of == block.id]
    ids = {i.id for i in made}
    if any(b.item_id in ids and (b.status is not BlockStatus.PLANNED or b.start <= moment) for b in store.list_blocks(conn)):
        raise Refused("Its catch-up has already started, so this answer can't change.")
    return [i.id for i in made]


def skip_deleted_catch_up(conn: sqlite3.Connection, item: Item) -> None:
    """A deleted catch-up item means the missed time is skipped, so its missed block says so.

    Nothing in the plan changes: catch-up and skip both leave the missed minutes covered.
    """
    if item.catch_up_of is None:
        return
    missed = [b for b in store.list_blocks(conn) if b.id == item.catch_up_of and b.missed_action is OnMiss.CATCH_UP]
    store.put_blocks(conn, [replace(b, missed_action=OnMiss.SKIP) for b in missed])


def _length(block: Block) -> int:
    return (block.end - block.start) // timedelta(minutes=1)


# Catch-up items


def catch_up_item(
    conn: sqlite3.Connection, settings: SolverSettings, block: Block, item: Item, missed_min: int, moment: datetime
) -> Item:
    """A flexible item to make up for a missed part, placed in the normal work frames before its deadline.

    A missed exact-time item takes RECORDING_FACTOR longer, rounded up to whole slots.
    """
    estimate = missed_min
    if item.flex_preset is FlexPreset.EXACT:
        estimate = math.ceil(missed_min * RECORDING_FACTOR / settings.slot_min) * settings.slot_min
    title = item.title.removeprefix(CATCH_UP_PREFIX)
    return Item(
        title=f"{CATCH_UP_PREFIX}{title}",
        flex_preset=FlexPreset.BEFORE_DEADLINE,
        estimate_min=estimate,
        deadline=catch_up_deadline(conn, settings, block, item, moment),
        max_chunk_min=item.max_chunk_min,
        keep_length=item.keep_length,
        checkable=True,
        on_miss=OnMiss.RESCHEDULE,
        catch_up_of=block.id,
    )


def catch_up_deadline(
    conn: sqlite3.Connection, settings: SolverSettings, block: Block, item: Item, moment: datetime
) -> datetime:
    return catch_up_due(conn, settings, block, item, moment)[0]


def catch_up_due(
    conn: sqlite3.Connection, settings: SolverSettings, block: Block, item: Item, moment: datetime
) -> tuple[datetime, str]:
    """A catch-up's deadline and why, for the page: "next session", "<item> is due" or "a week from now".

    Before the series' next occurrence, else before the earliest item that depends on it, else a week on.
    A choice less than MIN_CATCH_UP_LEAD away leaves too little room, so the next one is used.
    """
    choices: list[tuple[datetime | None, str]] = [(_next_occurrence_start(conn, settings, item), "next session")]
    dependents = [i for i in store.list_items(conn) if item.id in i.depends_on and i.deadline is not None]
    if dependents:
        first = min(dependents, key=lambda i: i.deadline or moment)
        choices.append((first.deadline, f"{first.title} is due"))
    for choice, why in choices:
        if choice is not None and choice >= moment + MIN_CATCH_UP_LEAD:
            return choice, why
    # Up to a slot boundary, so the item dialog shows 7:30pm rather than 7:24pm.
    return open_from_moment(max(block.end, moment) + CATCH_UP_FALLBACK, settings.slot_min), "a week from now"


def _next_occurrence_start(conn: sqlite3.Connection, settings: SolverSettings, item: Item) -> datetime | None:
    """When the series' next occurrence after this one begins: an exact item's start, else its day's midnight."""
    if item.series_id is None or item.occurrence_date is None:
        return None
    series = store.get_series(conn, item.series_id)
    if series is None:
        return None
    after = item.occurrence_date + timedelta(days=1)
    dates = occurrence_dates(series, after, after + NEXT_OCCURRENCE_LOOKAHEAD)
    if not dates:
        return None
    occurrence = occurrence_on(series, dates[0])
    if occurrence.flex_preset is FlexPreset.EXACT:
        start: datetime = occurrence.preset_params["start"]
        return start
    return _local_midnight(dates[0], settings.timezone)


def _local_midnight(day: date, timezone: str) -> datetime:
    return datetime.combine(day, time(), tzinfo=ZoneInfo(timezone)).astimezone(UTC)
