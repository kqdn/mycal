"""The week API: serve a week's stored plan as JSON (Milestone 3).

Not part of the solver: like demo.py and store.py, this module is a caller.
It reads the database and serves HTTP; planning goes through planner.py,
which calls solve(). The core modules never import it.

A week is planned the first time it is viewed and the plan is stored, so
later views are instant and the plan survives restarts. A week re-plans when
its plan is cleared (an import clears every week's plan), and adding or
deleting an item re-plans the weeks it touches right away.

Adding or editing an item is all or nothing: the change is tried on an
in-memory copy of the database, and only kept if it doesn't break a week that
fit before.
A week that already didn't fit keeps its old blocks, and the item's work
goes to its other weeks.

Work frames and rules apply to every week, so changing one re-plans every
week from this one on that has a plan, the same all-or-nothing way, and
clears the plans of earlier weeks so they re-plan when next viewed.

Series (Milestone 6) are added, changed and deleted here too. A series
reaches every week, so adding or changing one re-plans like a work frame
change; the planner creates its occurrences in each week it plans.

Check-ins (Milestone 7) are answered here, through checkins.py, all or
nothing like adding an item. Viewing a week or listing check-ins first turns
check-ins left too long into unanswered ones (checkins.CHECK_IN_GRACE).

All times in responses are UTC. The page converts them to the week's
timezone only for display.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from time import perf_counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mycal import checkins, store
from mycal.model import Block, BlockStatus, Constraint, FlexPreset, Item, ItemTemplate, OnMiss, Rule, Series, WorkFrame
from mycal.presets import every_day_session
from mycal.recurrence import occurrence_dates, occurrence_on
from mycal.planner import (
    create_occurrences,
    effective_item,
    effective_items,
    occurrence_last_day,
    due_week,
    frame_spans,
    local_monday,
    MAX_SPAN_WEEKS,
    monday,
    open_from_moment,
    plan_weeks,
    planned_down,
    remaining_min,
    span_for_item,
    PlannerTimeout,
    placed_min,
    Shortfall,
    shortfalls,
    span_for_view,
    waiting_on_broken_weeks,
    week_horizon,
    week_title,
    weeks_of_blocks,
    weeks_touched,
    WEEK as ONE_WEEK,
)
from mycal.settings import SolverSettings

# A child of uvicorn's logger, so lines show in the server console at INFO
# (uvicorn configures its loggers in the worker process, even with reload).
log = logging.getLogger("uvicorn.error.mycal")

# One request plans or writes at a time. The page prefetches neighbor weeks,
# and two requests planning the same week at once would both write a plan.
_lock = threading.Lock()

app = FastAPI(title="mycal")


@app.exception_handler(RequestValidationError)
async def readable_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    """422 with one sentence, like every other error, so the page can show `detail` as is."""
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"] if part not in ("body", "path", "query"))
    return JSONResponse(status_code=422, content={"detail": f"Check {field or 'the request'}: {first['msg']}."})


class BlockOut(BaseModel):
    id: UUID
    item_id: UUID
    title: str
    start: datetime
    end: datetime
    fixed: bool  # an exact event, not work the solver placed
    # The item's sessions in every week, in start order, for "Session 2 of 4".
    session: int
    sessions: int
    placed_min: int  # minutes of the item's work placed so far, in every week
    estimate_min: int | None  # None for an exact-time item
    editable: bool  # whether the edit dialog can change the item (not Custom)
    series_id: UUID | None = None  # set on an occurrence of a stored series
    # Check-ins (Milestone 7): planned, done, partial, missed or unanswered, the
    # minutes done (partial or done), and the policy that ran on the missed part.
    checkable: bool = False
    status: str = BlockStatus.PLANNED.value
    done_min: int | None = None
    missed_action: str | None = None
    history: bool = False  # it has check-in history, so deleting it archives it instead
    on_miss: str = "reschedule"  # what a No does (Skip for an exact item set to Reschedule)


class CheckInOut(BaseModel):
    """A block waiting for a check-in, or for a choice about its missed part (an Ask item)."""

    block_id: UUID
    item_id: UUID
    title: str
    start: datetime
    end: datetime
    fixed: bool
    status: str  # planned (not answered yet) or the answer that waits for a choice
    done_min: int | None
    on_miss: str  # what a No does: the item's policy, with Reschedule as Skip for an exact item
    choices: list[str]  # what the missed part can do instead


class CheckInIn(BaseModel):
    """An answer. `done_min` is for Partly; `action` is the choice for the missed part, needed for Ask items."""

    answer: Literal["yes", "partly", "no"]
    done_min: int | None = None
    action: Literal["reschedule", "catch_up", "skip"] | None = None
    accept_shortfall: bool = False  # see ItemIn


class SpanOut(BaseModel):
    start: datetime
    end: datetime


class ItemRef(BaseModel):
    id: UUID
    title: str
    estimate_min: int | None  # None when the item has no estimate
    reason: str | None = None  # why it isn't scheduled, when it is waiting on a week that can't be planned
    sessions: int = 0  # how many blocks it has in every week
    editable: bool = False  # whether the edit dialog can change the item (not Custom)
    series_id: UUID | None = None  # set on an occurrence of a stored series
    history: bool = False  # it has check-in history, so deleting it archives it instead


class RepeatOut(BaseModel):
    """How a series repeats, for the details popover's "Repeats" line.

    A days item ("any of these days", "every one of these days") repeats as a
    whole week: `per_week` is true and `weekdays` is empty.
    """

    id: UUID
    freq: Literal["daily", "weekly"]
    interval: int
    weekdays: list[int]
    per_week: bool
    end_date: date | None


class ShortfallOut(BaseModel):
    """An "N times a week" item in the week that gets fewer sessions than it needs, not yet accepted."""

    item_id: UUID
    title: str
    sessions: int
    gets: int
    message: str  # "Workout gets 2 of 3 sessions this week: only Wed and Fri are left."


class WeekOut(BaseModel):
    week_start: date
    timezone: str
    slot_min: int  # so the page can show planned lengths without hardcoding 15
    feasible: bool
    blocks: list[BlockOut]
    frames: list[SpanOut]  # work-frame time inside the week, merged
    unscheduled: list[ItemRef]
    series: list[RepeatOut] = []  # how each series with an occurrence in the week repeats
    shortfalls: list[ShortfallOut] = []



def now() -> datetime:
    """The current time. Tests replace it to plan as of a fixed moment."""
    return datetime.now(UTC)


@contextmanager
def database() -> Iterator[tuple[sqlite3.Connection, SolverSettings]]:
    """A connection plus the saved settings, one at a time. 404 if nothing was imported yet."""
    with _lock:
        conn = store.connect(store.db_path())
        try:
            settings = store.load_settings(conn)
            if settings is None:
                raise HTTPException(
                    status_code=404,
                    detail="Nothing imported yet. Run uv run mycal-import weeks/<week-start>.toml in solver/.",
                )
            yield conn, settings
        finally:
            conn.close()


@app.get("/api/weeks/{week_start}")
def get_week(week_start: date) -> WeekOut:
    """The week's stored plan, planning it first if it has none. A week that can't be planned is still 200."""
    with database() as (conn, settings):
        moment = now()
        _expire_check_ins(conn, settings, moment)
        try:
            feasible = _status(conn, settings, week_start, moment)
        except PlannerTimeout as error:
            log.warning("%s: %s", week_start, error)
            raise HTTPException(status_code=503, detail=VIEW_TIMED_OUT) from error
        return week_out(conn, settings, week_start, feasible, moment)


class ItemIn(BaseModel):
    """A new item as the New item dialog collects it: local dates and times in my timezone.

    `week_start` is the week being viewed (its Monday). A "days" or "every_day" item
    belongs to it, and it is the week the response shows. An "every_day" item is a
    days item with one session of `session_min` on each chosen day.
    """

    week_start: date
    title: str
    preset: Literal["exact", "day", "day_range", "days", "every_day", "before_deadline"]
    day: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    weekdays: list[int] | None = None
    deadline_date: date | None = None
    deadline_time: time | None = None
    estimate_min: int | None = None
    max_chunk_min: int | None = None
    one_block_per_day: bool = False
    session_min: int | None = None
    # Check-ins (Milestone 7). Left out: checkable unless it is an exact-time item, and Reschedule
    # (Skip for an exact-time item, which can't move). Left out when editing: kept as stored.
    checkable: bool | None = None
    on_miss: Literal["reschedule", "catch_up", "skip", "ask"] | None = None
    # Set when sending again after a 409 that said an "N times a week" item gets fewer sessions.
    accept_shortfall: bool = False


class ItemFormOut(BaseModel):
    """A stored item in the dialog's terms, to fill in the edit dialog. Lengths are as typed, not rounded.

    `week_start` is the item's own week for "days" and "every_day" items (send it
    back as is). `editable` is false for Custom items, which the dialog can't show.
    """

    id: UUID
    source: str | None  # the week file it was imported from, or None if added in the app
    editable: bool
    series_id: UUID | None = None  # set on an occurrence of a series, which can't be made to repeat again
    week_start: date
    title: str
    preset: Literal["exact", "day", "day_range", "days", "every_day", "before_deadline", "custom"]
    day: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    weekdays: list[int] | None = None
    deadline_date: date | None = None
    deadline_time: time | None = None
    estimate_min: int | None = None
    max_chunk_min: int | None = None
    one_block_per_day: bool = False
    session_min: int | None = None
    checkable: bool = False
    on_miss: Literal["reschedule", "catch_up", "skip", "ask"] = "reschedule"


class Invalid(ValueError):
    """A request the dialog should explain in words; it becomes a 422 with that message."""


NO_DAY_LEFT = "None of these days has room left this week."
DOES_NOT_FIT = (
    "It doesn't fit: there isn't enough free time in its days and work frames. "
    "Try more days, a later deadline or a smaller estimate."
)


# A planner timeout is not "doesn't fit": the solver ran out of work budget
# before finding any arrangement, which proves nothing either way.
VIEW_TIMED_OUT = "The planner ran out of time planning this week. Its old plan is kept."
ADD_TIMED_OUT = (
    "The planner ran out of time before finishing, so nothing was added. "
    "Try again with fewer days or a smaller estimate."
)
EDIT_TIMED_OUT = (
    "The planner ran out of time before finishing, so nothing was changed. "
    "Try again with fewer days or a smaller estimate."
)
CUSTOM_NOT_EDITABLE = "Change a Custom item in its week file."
ALREADY_STARTED = "It has already started, so its time can't change."
ITEM_GONE = "That item no longer exists."


def waits_on_broken_week(weeks: list[date]) -> str:
    named = " and ".join(f"the week of {week_title(w)}" for w in weeks)
    return f"Nothing was added: {named} already can't be planned. Make room there first, for example by deleting something."


@app.post("/api/items", status_code=201)
def add_item(request: ItemIn) -> WeekOut:
    """Add an item, re-plan the weeks it touches and return the viewed week. 422 if it doesn't fit."""
    with database() as (conn, settings):
        moment = now()
        try:
            item = to_item(request, settings, moment)
        except Invalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if request.preset == "every_day":
            frames = store.list_work_frames(conn)
            if effective_item(item, [], frames, settings, moment).estimate_min == 0:
                raise HTTPException(status_code=422, detail=NO_DAY_LEFT)

        first, last = span_for_item(item, settings.timezone, moment)
        _put_and_plan(conn, settings, item, first, last, moment, ADD_TIMED_OUT, request.accept_shortfall)
        log.info("added %r, re-planned %s to %s", item.title, first, last)
        return week_out(conn, settings, request.week_start, _status_or_stored(conn, settings, request.week_start, moment), moment)


@app.delete("/api/items/{item_id}")
def delete_item(item_id: UUID, week: date) -> WeekOut:
    """Delete an item and its blocks, re-plan the weeks they were in, and return the viewed `week`.

    An item with check-in history is archived instead: its finished blocks stay
    as history, its sessions ahead are removed and it leaves the week view.
    """
    with database() as (conn, settings):
        if store.get_item(conn, item_id) is None or store.is_archived(conn, item_id):
            raise HTTPException(status_code=404, detail=ITEM_GONE)
        moment = now()
        blocks = store.list_blocks(conn)
        weeks = weeks_of_blocks([b for b in blocks if b.item_id == item_id], settings.timezone)
        _skip_occurrence(conn, item_id)
        if item_id in _with_history(blocks):
            store.archive_item(conn, item_id, moment)
        else:
            store.delete_item(conn, item_id)
        try:
            if weeks:
                plan_weeks(conn, settings, weeks[0], weeks[-1], moment)
        except PlannerTimeout as error:
            # The item is gone either way. Weeks that didn't finish stay unmarked
            # and re-plan when next viewed.
            log.warning("re-planning after deleting %s: %s", item_id, error)
        return week_out(conn, settings, week, _status_or_stored(conn, settings, week, moment), moment)


@app.get("/api/items/{item_id}")
def get_item(item_id: UUID) -> ItemFormOut:
    """An item in the dialog's terms, to fill in the edit dialog."""
    with database() as (conn, settings):
        item = store.get_item(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=ITEM_GONE)
        return from_item(item, store.item_source(conn, item_id), settings)


@app.put("/api/items/{item_id}")
def update_item(item_id: UUID, request: ItemIn, week: date) -> WeekOut:
    """Change an item, re-plan the weeks its old and new sessions touch, and return the viewed `week`.

    Like adding, it's all or nothing: 422 if the change doesn't fit, and then
    nothing changes. Fields the dialog doesn't show (dependencies, parent,
    series, source) are kept, and so are checkable and on_miss when left out. Sessions that already started
    or are done stay and count toward the work.
    """
    with database() as (conn, settings):
        old = store.get_item(conn, item_id)
        if old is None:
            raise HTTPException(status_code=404, detail=ITEM_GONE)
        if not editable(old):
            raise HTTPException(status_code=422, detail=CUSTOM_NOT_EDITABLE)
        moment = now()
        blocks = [b for b in store.list_blocks(conn) if b.item_id == item_id]
        moved = _when(request) != _when(from_item(old, None, settings))
        try:
            # A changed time must still lie ahead; an unchanged one may have passed (fix a past item's title).
            new = _edited(old, to_item(request, settings, moment, check_past=moved))
            if request.checkable is None:
                new.checkable = old.checkable
            if request.on_miss is None:
                new.on_miss = old.on_miss
        except Invalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if moved and old.flex_preset is FlexPreset.EXACT and any(b.start <= moment for b in blocks):
            raise HTTPException(status_code=422, detail=ALREADY_STARTED)
        if moved and request.preset == "every_day":
            if effective_item(new, [], store.list_work_frames(conn), settings, moment).estimate_min == 0:
                raise HTTPException(status_code=422, detail=NO_DAY_LEFT)

        # Weeks in play: where its current plan is now, and where the changed item can go.
        open_from = open_from_moment(moment, settings.slot_min)
        current = [b for b in blocks if b.status is BlockStatus.PLANNED and not b.locked and b.start >= open_from]
        weeks = weeks_of_blocks(current, settings.timezone)
        if weeks_touched(new, settings.timezone, moment):
            weeks += span_for_item(new, settings.timezone, moment)
        if weeks:
            _put_and_plan(conn, settings, new, min(weeks), max(weeks), moment, EDIT_TIMED_OUT, request.accept_shortfall)
        else:
            store.put_item(conn, new)  # nothing left to place, say a past item's new title
        if new.series_id is not None:
            store.mark_hand_edited(conn, new.id)  # a series edit leaves it alone from now on
        log.info("edited %r, re-planned %s", new.title, f"{min(weeks)} to {max(weeks)}" if weeks else "nothing")
        return week_out(conn, settings, week, _status_or_stored(conn, settings, week, moment), moment)


# Check-ins (Milestone 7)


BLOCK_GONE = "That session no longer exists."
CHECK_IN_DOES_NOT_FIT = "There isn't room left for the time you missed. Pick Skip or Catch up instead."
CATCH_UP_DOES_NOT_FIT = "There isn't room for a catch-up before it's due. Pick Skip instead."
CHECK_IN_TIMED_OUT = "The planner ran out of time before finishing, so the answer wasn't saved. Try again."


@app.get("/api/check-ins")
def list_check_ins() -> list[CheckInOut]:
    """Checkable blocks that ended without an answer, and Ask blocks waiting for a choice, earliest first."""
    with database() as (conn, settings):
        moment = now()
        _expire_check_ins(conn, settings, moment)
        return [_check_in_out(block, item) for block, item in checkins.pending(conn, moment)]


@app.post("/api/blocks/{block_id}/check-in")
def check_in(block_id: UUID, request: CheckInIn, week: date) -> WeekOut:
    """Answer a check-in (or change an answer), run the on-miss policy, re-plan, and return the viewed `week`.

    All or nothing, like adding an item: 422 with a sentence if the missed part
    can't go anywhere, and then nothing is saved.
    """
    with database() as (conn, settings):
        moment = now()
        block = next((b for b in store.list_blocks(conn) if b.id == block_id), None)
        if block is None:
            raise HTTPException(status_code=404, detail=BLOCK_GONE)
        item = store.get_item(conn, block.item_id)
        assert item is not None  # blocks go with their item
        chosen = None if request.action is None else OnMiss(request.action)
        try:
            resolution = checkins.resolve(
                conn, settings, block, item, checkins.Answer(request.answer), moment, request.done_min, chosen
            )
        except checkins.Refused as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        _save_check_ins(conn, settings, [resolution], moment, f"check-in for {item.title!r}", request.accept_shortfall)
        log.info("checked in %r: %s", item.title, request.answer)
        return week_out(conn, settings, week, _status_or_stored(conn, settings, week, moment), moment)


def _expire_check_ins(conn: sqlite3.Connection, settings: SolverSettings, moment: datetime) -> None:
    """Count check-ins left unanswered too long as No. If their policies can't fit, they wait for a choice instead."""
    resolutions = checkins.expire_all(conn, settings, moment)
    if not resolutions:
        return
    try:
        _save_check_ins(conn, settings, resolutions, moment, "unanswered check-ins")
    except HTTPException:
        checkins.apply(conn, [checkins.waiting(r) for r in resolutions])
    log.info("%d check-in(s) went unanswered", len(resolutions))


def _save_check_ins(
    conn: sqlite3.Connection,
    settings: SolverSettings,
    resolutions: list[checkins.Resolution],
    moment: datetime,
    log_name: str,
    accept_shortfall: bool | None = None,
) -> None:
    """Store answers and re-plan from this week on, all or nothing (HTTPException and nothing saved).

    Refused if a week that fit stops fitting, a catch-up isn't placed in full,
    or an item has more unplaced work than before. An answer that leaves an
    "N times a week" item with fewer sessions needs accept_shortfall (else
    409); None, for check-ins that went unanswered, asks nothing and leaves
    it to the week's banner.
    """
    items = {i.id: i for i in store.list_items(conn)}
    answered = [items[r.block.item_id] for r in resolutions]
    catch_ups = [r.catch_up for r in resolutions if r.catch_up is not None]
    first = local_monday(moment, settings.timezone)
    touched = [w for i in answered + catch_ups for w in weeks_touched(i, settings.timezone, moment)]
    last = max([first + (MAX_SPAN_WEEKS - 1) * ONE_WEEK, *touched])

    def unplaced(at: sqlite3.Connection, item: Item) -> int:
        blocks = store.list_blocks(at)
        return remaining_min(effective_item(item, blocks, store.list_work_frames(at), settings, moment), blocks)

    before = {i.id: unplaced(conn, i) for i in answered}
    short_before = _shortfalls(conn, settings, moment)

    def all_placed(trial: sqlite3.Connection, _after: dict[date, bool]) -> None:
        if accept_shortfall is not None:
            _confirm_shortfalls(trial, settings, moment, short_before, accept_shortfall, {i.id for i in answered})
        if any(unplaced(trial, c) > 0 for c in catch_ups):
            raise HTTPException(status_code=422, detail=CATCH_UP_DOES_NOT_FIT)
        if any(unplaced(trial, i) > before[i.id] for i in answered):
            raise HTTPException(status_code=422, detail=CHECK_IN_DOES_NOT_FIT)

    _change_and_plan(
        conn,
        settings,
        lambda trial: checkins.apply(trial, resolutions),
        first,
        last,
        moment,
        log_name=log_name,
        timed_out=CHECK_IN_TIMED_OUT,
        broke=lambda _weeks: CHECK_IN_DOES_NOT_FIT,
        check=all_placed,
    )


# Fewer sessions for "N times a week" items


@app.post("/api/shortfalls/{item_id}/accept")
def accept_shortfall(item_id: UUID, week: date) -> WeekOut:
    """Hide the banner for an item getting fewer sessions, until it drops further. Returns the viewed `week`."""
    with database() as (conn, settings):
        moment = now()
        short = next((s for s in _shortfalls(conn, settings, moment) if s.item_id == item_id), None)
        if short is not None:
            store.acknowledge_shortfall(conn, item_id, short.gets)
        return week_out(conn, settings, week, _status_or_stored(conn, settings, week, moment), moment)


def _shortfalls(conn: sqlite3.Connection, settings: SolverSettings, moment: datetime) -> list[Shortfall]:
    return shortfalls(store.list_items(conn), store.list_blocks(conn), store.list_work_frames(conn), settings, moment)


def _confirm_shortfalls(
    trial: sqlite3.Connection,
    settings: SolverSettings,
    moment: datetime,
    before: list[Shortfall],
    accept: bool,
    changed: set[UUID],
) -> None:
    """409 with the sentence to confirm if the change leaves a changed item with fewer sessions than before.

    Only the changed items count: a shortfall depends on the item's own days,
    so a change can't cause one in another item. Once accepted, the change
    counts as acknowledged, so no banner follows it.
    """
    was = {s.item_id: s.gets for s in before}
    found = _shortfalls(trial, settings, moment)
    new = [s for s in found if s.item_id in changed and s.gets < was.get(s.item_id, s.sessions)]
    if not new:
        return
    if not accept:
        raise HTTPException(status_code=409, detail=" ".join(shortfall_message(s, settings, moment) for s in new))
    for s in new:
        store.acknowledge_shortfall(trial, s.item_id, s.gets)


def shortfall_message(short: Shortfall, settings: SolverSettings, moment: datetime) -> str:
    """"Workout gets 2 of 3 sessions this week: only Wed and Fri are left." """
    this_week = short.week == local_monday(moment, settings.timezone)
    when = "this week" if this_week else f"the week of {week_title(short.week)}"
    names = [f"{day:%a}" for day in short.days_left]
    if not names:
        left = "none of its days are left"
    elif len(names) == 1:
        left = f"only {names[0]} is left"
    else:
        left = f"only {', '.join(names[:-1])} and {names[-1]} are left"
    return f"{short.title} gets {short.gets} of {short.sessions} sessions {when}: {left}."


def _with_history(blocks: list[Block]) -> set[UUID]:
    """Items with check-in history: a block that was answered (done, partial, missed or unanswered)."""
    return {b.item_id for b in blocks if b.status is not BlockStatus.PLANNED}


def _check_in_out(block: Block, item: Item) -> CheckInOut:
    policy = checkins.policy_for(item)
    choices = [OnMiss.CATCH_UP, OnMiss.SKIP] if item.flex_preset is FlexPreset.EXACT else [OnMiss.RESCHEDULE, OnMiss.CATCH_UP, OnMiss.SKIP]
    return CheckInOut(
        block_id=block.id,
        item_id=item.id,
        title=item.title,
        start=block.start,
        end=block.end,
        fixed=item.flex_preset is FlexPreset.EXACT,
        status=block.status.value,
        done_min=block.actual_min,
        on_miss=policy.value,
        choices=[c.value for c in choices],
    )


# Series


class SeriesIn(ItemIn):
    """A repeating item: the New item dialog's fields plus how it repeats.

    The item fields describe every occurrence; their dates are ignored, since
    each occurrence's date fills them in. `repeat_weekdays` are the days a
    weekly series falls on. A days item ("days", "every_day") repeats as a
    whole week, so it takes no repeat days and its series starts on the Monday
    of `start_date`'s week.
    """

    freq: Literal["daily", "weekly"] = "weekly"
    interval: int = 1
    repeat_weekdays: list[int] = []
    start_date: date
    end_date: date | None = None


class SeriesFormOut(BaseModel):
    """A stored series in the dialog's terms, to fill in the edit dialog."""

    id: UUID
    source: str | None
    title: str
    preset: Literal["exact", "day", "day_range", "days", "every_day", "before_deadline"]
    start_time: time | None = None
    end_time: time | None = None
    weekdays: list[int] | None = None
    deadline_time: time | None = None
    estimate_min: int | None = None
    max_chunk_min: int | None = None
    one_block_per_day: bool = False
    session_min: int | None = None
    checkable: bool = False
    on_miss: Literal["reschedule", "catch_up", "skip", "ask"] = "reschedule"
    freq: Literal["daily", "weekly"]
    interval: int
    repeat_weekdays: list[int]
    start_date: date
    end_date: date | None = None


SERIES_GONE = "That repeating item no longer exists."
ALREADY_REPEATS = "It already repeats. Edit the series instead."
SERIES_TIMED_OUT = (
    "The planner ran out of time before finishing, so nothing was changed. "
    "Try again, or change fewer weeks at once."
)


@app.post("/api/series", status_code=201)
def add_series(request: SeriesIn) -> WeekOut:
    """Add a repeating item and re-plan every week from this one on, like a work frame. 422 if a week stops fitting."""
    with database() as (conn, settings):
        try:
            series = to_series(request, settings, now())
        except Invalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _change_everywhere(conn, settings, lambda trial: store.put_series(trial, series), request.week_start, repr(series.title))


@app.post("/api/items/{item_id}/repeat")
def repeat_item(item_id: UUID, request: SeriesIn, week: date) -> WeekOut:
    """Turn a one-off item into a series, with the item as its occurrence on the item's own date.

    The item keeps its id and its sessions, so done work stays. If it hasn't
    started and the rule falls on its date, it is rebuilt from the new
    template; otherwise it stays as it is and counts as edited by hand. Its
    date may have passed; only a start date other than the item's own has to
    lie ahead. Re-plans like adding a series, all or nothing.
    """
    with database() as (conn, settings):
        old = store.get_item(conn, item_id)
        if old is None:
            raise HTTPException(status_code=404, detail=ITEM_GONE)
        if old.series_id is not None:
            raise HTTPException(status_code=422, detail=ALREADY_REPEATS)
        if not editable(old):
            raise HTTPException(status_code=422, detail=CUSTOM_NOT_EDITABLE)
        moment = now()
        day = _item_date(old, settings)
        if request.preset in ("days", "every_day"):
            day = monday(day)
        try:
            series = to_series(request, settings, moment, check_past=request.start_date != day)
        except Invalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        rebuild = old.id in {i.id for i in _not_started_items([old], conn, settings, moment)} and bool(
            occurrence_dates(series, day, day)
        )
        base = occurrence_on(series, day) if rebuild else old
        linked = replace(
            base,
            id=old.id,
            parent_id=old.parent_id,
            depends_on=old.depends_on,
            catch_up_of=old.catch_up_of,
            series_id=series.id,
            occurrence_date=day,
        )

        def change(trial: sqlite3.Connection) -> None:
            store.put_series(trial, series)
            store.put_item(trial, linked)
            if not rebuild:
                store.mark_hand_edited(trial, linked.id)

        return _change_everywhere(conn, settings, change, week, repr(series.title))


def _item_date(item: Item, settings: SolverSettings) -> date:
    """The local date a one-off item belongs to: its day, its week's Monday, or its due date."""
    form = from_item(item, None, settings)
    if form.preset in ("days", "every_day"):
        return form.week_start
    if form.preset == "before_deadline":
        assert form.deadline_date is not None
        return form.deadline_date
    assert form.day is not None
    return form.day


@app.get("/api/series/{series_id}")
def get_series(series_id: UUID) -> SeriesFormOut:
    with database() as (conn, settings):
        series = store.get_series(conn, series_id)
        if series is None:
            raise HTTPException(status_code=404, detail=SERIES_GONE)
        return from_series(series, store.series_source(conn, series_id))


@app.put("/api/series/{series_id}")
def update_series(series_id: UUID, request: SeriesIn, week: date) -> WeekOut:
    """Change a series. Occurrences that haven't started are rebuilt from the new template,
    except ones edited by hand; started and past ones stay as they are. All or nothing."""
    with database() as (conn, settings):
        old = store.get_series(conn, series_id)
        if old is None:
            raise HTTPException(status_code=404, detail=SERIES_GONE)
        moment = now()
        try:
            # An unchanged start may have passed, so an old series can still be edited.
            new = to_series(request, settings, moment, check_past=request.start_date != old.start_date)
        except Invalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        new = replace(new, id=old.id, skipped_dates=old.skipped_dates)

        def change(trial: sqlite3.Connection) -> None:
            store.put_series(trial, new)
            for occurrence in _not_started(trial, settings, series_id, moment):
                if not store.hand_edited(trial, occurrence.id):
                    store.delete_item(trial, occurrence.id)  # the planner creates it again from the new template

        return _change_everywhere(conn, settings, change, week, repr(new.title))


@app.delete("/api/series/{series_id}")
def delete_series(series_id: UUID, week: date) -> WeekOut:
    """End a series: occurrences that haven't started are deleted, and past and started ones stay
    (completion history). A series with nothing left is deleted whole."""
    with database() as (conn, settings):
        series = store.get_series(conn, series_id)
        if series is None:
            raise HTTPException(status_code=404, detail=SERIES_GONE)
        moment = now()
        gone = {o.id for o in _not_started(conn, settings, series_id, moment)}
        weeks = weeks_of_blocks([b for b in store.list_blocks(conn) if b.item_id in gone], settings.timezone)
        for item_id in gone:
            store.delete_item(conn, item_id)
        left = [i.occurrence_date for i in store.list_items(conn) if i.series_id == series_id and i.occurrence_date]
        if left:
            store.put_series(conn, replace(series, end_date=max(left)))
        else:
            store.delete_series(conn, series_id)
        try:
            if weeks:
                plan_weeks(conn, settings, weeks[0], weeks[-1], moment)
        except PlannerTimeout as error:
            log.warning("re-planning after ending series %s: %s", series_id, error)
        log.info("ended %r", series.title)
        return week_out(conn, settings, week, _status_or_stored(conn, settings, week, moment), moment)


def _not_started(conn: sqlite3.Connection, settings: SolverSettings, series_id: UUID, moment: datetime) -> list[Item]:
    """The series' occurrences that still lie ahead: none of their sessions started and they have a day left."""
    occurrences = [i for i in store.list_items(conn) if i.series_id == series_id]
    return _not_started_items(occurrences, conn, settings, moment)


def _not_started_items(
    items: list[Item], conn: sqlite3.Connection, settings: SolverSettings, moment: datetime
) -> list[Item]:
    """The items (occurrences, or one being made an occurrence) none of whose sessions started, with a day left."""
    today = moment.astimezone(ZoneInfo(settings.timezone)).date()
    started = {b.item_id for b in store.list_blocks(conn) if b.start <= moment or b.status is not BlockStatus.PLANNED}

    def last_day(item: Item) -> date:
        if item.occurrence_date is not None:
            return occurrence_last_day(item)
        day = _item_date(item, settings)
        return day + timedelta(days=6) if item.flex_preset is FlexPreset.DAYS else day

    return [
        i
        for i in items
        if i.id not in started
        and last_day(i) >= today
        and not (i.flex_preset is FlexPreset.EXACT and i.preset_params["start"] <= moment)
    ]


def _skip_occurrence(conn: sqlite3.Connection, item_id: UUID) -> None:
    """Before deleting an occurrence, add its date to its series' skipped dates, so the planner doesn't create it again."""
    item = store.get_item(conn, item_id)
    if item is None or item.series_id is None or item.occurrence_date is None:
        return
    series = store.get_series(conn, item.series_id)
    if series is not None:
        store.put_series(conn, replace(series, skipped_dates=sorted({*series.skipped_dates, item.occurrence_date})))


def to_series(request: SeriesIn, settings: SolverSettings, moment: datetime, check_past: bool = True) -> Series:
    """Turn the dialog's fields into a Series. Raises Invalid with a message for the dialog.

    The template's lengths and checks come from to_item on the first
    occurrence, so a series is refused for the same reasons as a one-off item.
    """
    title = request.title.strip()
    if not title:
        raise Invalid("Give the item a title.")
    if request.interval < 1:
        raise Invalid("Repeat every 1 or more.")
    per_week = request.preset in ("days", "every_day")
    start = request.start_date
    if per_week:
        if request.freq != "weekly":
            raise Invalid("An item on chosen days repeats every week, not every day.")
        start = monday(start)
        rule = Rule("weekly", request.interval, [0])  # one occurrence a week, dated its Monday
    elif request.freq == "weekly":
        weekdays = sorted(set(request.repeat_weekdays))
        if not weekdays or any(d not in range(7) for d in weekdays):
            raise Invalid("Pick at least one day to repeat on.")
        rule = Rule("weekly", request.interval, weekdays)
    else:
        rule = Rule("daily", request.interval)

    today = moment.astimezone(ZoneInfo(settings.timezone)).date()
    if check_past and start < (monday(today) if per_week else today):
        raise Invalid("A repeating item can't start in the past.")
    if request.end_date is not None and request.end_date < start:
        raise Invalid("The end date is before the start date.")

    # The first occurrence, checked like a one-off item. A rule repeats within interval weeks.
    probe = Series(title, rule, settings.timezone, start, ItemTemplate(FlexPreset.DAY), request.end_date)
    horizon = start + timedelta(weeks=request.interval + 1)
    first = next(iter(occurrence_dates(probe, start, min(horizon, request.end_date or horizon))), None)
    if first is None:
        raise Invalid("No day between the start and end dates matches how it repeats.")
    sample = request.model_copy(update={"day": first, "deadline_date": first, "week_start": monday(first)})
    item = to_item(sample, settings, moment, check_past=False)

    params: dict[str, Any] = {}
    if request.preset in ("exact", "day_range"):
        params = {"start_time": request.start_time, "end_time": request.end_time}
    elif per_week:
        params = {k: v for k, v in item.preset_params.items() if k != "week"}
    template = ItemTemplate(
        flex_preset=item.flex_preset,
        preset_params=params,
        estimate_min=item.estimate_min,
        deadline_time=request.deadline_time if item.flex_preset is FlexPreset.BEFORE_DEADLINE else None,
        max_chunk_min=item.max_chunk_min,
        one_block_per_day=item.one_block_per_day,
        checkable=item.checkable,
        on_miss=item.on_miss,
    )
    return Series(title, rule, settings.timezone, start, template, request.end_date)


def from_series(series: Series, source: str | None) -> SeriesFormOut:
    """The series in the dialog's terms: the inverse of to_series."""
    t = series.template
    params = t.preset_params
    fields: dict[str, Any] = {
        "id": series.id,
        "source": source,
        "title": series.title,
        "preset": t.flex_preset.value,
        "start_time": params.get("start_time"),
        "end_time": params.get("end_time"),
        "deadline_time": t.deadline_time,
        "estimate_min": t.estimate_min,
        "max_chunk_min": t.max_chunk_min,
        "one_block_per_day": t.one_block_per_day,
        "checkable": t.checkable,
        "on_miss": t.on_miss.value,
        "freq": series.rule.freq,
        "interval": series.rule.interval,
        "repeat_weekdays": series.rule.weekdays,
        "start_date": series.start_date,
        "end_date": series.end_date,
    }
    if t.flex_preset is FlexPreset.DAYS:
        fields |= {"weekdays": list(params["weekdays"]), "repeat_weekdays": []}
        if (session := every_day_session(params)) is not None:
            fields |= {"preset": "every_day", "session_min": session, "estimate_min": None, "max_chunk_min": None}
            fields["one_block_per_day"] = False  # every-day items set it themselves
    return SeriesFormOut(**fields)


def repeat_out(series: Series) -> RepeatOut:
    per_week = series.template.flex_preset is FlexPreset.DAYS
    return RepeatOut(
        id=series.id,
        freq=series.rule.freq,
        interval=series.rule.interval,
        weekdays=[] if per_week else series.rule.weekdays,
        per_week=per_week,
        end_date=series.end_date,
    )


# Work frames


class FrameIn(BaseModel):
    """A work frame as the Frame dialog collects it: local times in my timezone.

    An end before the start crosses midnight; each weekday is the day the frame starts on.
    """

    name: str
    weekdays: list[int]
    start_time: time
    end_time: time


class FrameOut(FrameIn):
    id: UUID


FRAME_GONE = "That work frame no longer exists."
CHANGE_TIMED_OUT = "The planner ran out of time before finishing, so nothing was changed. Try again."


def weeks_would_break(weeks: list[date]) -> str:
    named = " and ".join(f"the week of {week_title(w)}" for w in weeks)
    return f"Nothing changed: {named} wouldn't fit. Loosen the change, or make room there first."


@app.get("/api/frames")
def list_frames() -> list[FrameOut]:
    """Every work frame, by first weekday and then start time."""
    with database() as (conn, _settings):
        frames = sorted(store.list_work_frames(conn), key=lambda f: (min(f.weekdays, default=7), f.start_time))
        return [FrameOut(id=f.id, name=f.name, weekdays=sorted(f.weekdays), start_time=f.start_time, end_time=f.end_time) for f in frames]


@app.post("/api/frames", status_code=201)
def add_frame(request: FrameIn, week: date) -> WeekOut:
    """Add a work frame, re-plan every planned week from this one on, and return the viewed `week`."""
    with database() as (conn, settings):
        frame = _to_frame(request, settings)
        return _change_everywhere(conn, settings, lambda trial: store.put_work_frame(trial, frame), week, f"frame {frame.name!r}")


@app.put("/api/frames/{frame_id}")
def update_frame(frame_id: UUID, request: FrameIn, week: date) -> WeekOut:
    """Change a work frame, re-plan, and return the viewed `week`. 422 and no change if a week would stop fitting."""
    with database() as (conn, settings):
        if frame_id not in {f.id for f in store.list_work_frames(conn)}:
            raise HTTPException(status_code=404, detail=FRAME_GONE)
        frame = replace(_to_frame(request, settings), id=frame_id)
        return _change_everywhere(conn, settings, lambda trial: store.put_work_frame(trial, frame), week, f"frame {frame.name!r}")


@app.delete("/api/frames/{frame_id}")
def delete_frame(frame_id: UUID, week: date) -> WeekOut:
    """Delete a work frame, re-plan, and return the viewed `week`. 422 and no change if a week would stop fitting."""
    with database() as (conn, settings):
        if frame_id not in {f.id for f in store.list_work_frames(conn)}:
            raise HTTPException(status_code=404, detail=FRAME_GONE)
        return _change_everywhere(conn, settings, lambda trial: store.delete_work_frame(trial, frame_id), week, f"frame {frame_id}")


def _to_frame(request: FrameIn, settings: SolverSettings) -> WorkFrame:
    """The dialog's fields as a WorkFrame in my timezone, or a 422 with the dialog's message."""
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Give it a name, like Weekdays.")
    if not request.weekdays or any(day not in range(7) for day in request.weekdays):
        raise HTTPException(status_code=422, detail="Pick at least one day.")
    if request.start_time == request.end_time:
        raise HTTPException(status_code=422, detail="Start and end can't be the same time.")
    return WorkFrame(name, sorted(set(request.weekdays)), request.start_time, request.end_time, settings.timezone)


# Rules (constraints)

RuleKind = Literal["daily_limit", "time_preference", "rest_between"]
KIND_NAMES = {"daily_limit": "daily limit", "time_preference": "time preference", "rest_between": "rest days"}
MAX_RANGES = 6


class RangeIn(BaseModel):
    """Local times of day on some weekdays (0 = Monday). An end before the start crosses midnight."""

    weekdays: list[int]
    start_time: time
    end_time: time


class RuleIn(BaseModel):
    """A rule as the Rule dialog collects it. Only the fields of its kind are used.

    `every_item` covers every item; otherwise `item_ids` and `series_ids` name
    what it covers, and at least one is needed. A daily limit counts the whole
    day, so it has no targets.
    """

    kind: RuleKind
    max_min: int | None = None  # daily_limit
    weekdays: list[int] | None = None  # daily_limit
    mode: Literal["prefer", "avoid"] = "prefer"  # time_preference
    ranges: list[RangeIn] | None = None  # time_preference
    min_gap_days: int | None = None  # rest_between
    every_item: bool = False
    item_ids: list[UUID] = []
    series_ids: list[UUID] = []


class TargetOut(BaseModel):
    id: UUID
    kind: Literal["item", "series"]
    title: str
    week_start: date | None = None  # a one-off item's week; None for a series


class RuleOut(BaseModel):
    """A stored rule in the dialog's terms. `source` is the week file it came from, or None."""

    id: UUID
    kind: RuleKind
    source: str | None
    max_min: int | None = None
    weekdays: list[int] | None = None
    mode: Literal["prefer", "avoid"] | None = None
    ranges: list[RangeIn] | None = None
    min_gap_days: int | None = None
    every_item: bool = False
    targets: list[TargetOut] = []


RULE_GONE = "That rule no longer exists."
KIND_FIXED = "A rule's kind can't change. Delete it and add another."
PICK_TARGETS = "Pick at least one item, or choose Every item."


@app.get("/api/rules")
def list_rules() -> list[RuleOut]:
    """Every rule: daily limits, then time preferences, then rest days, each in the order added."""
    with database() as (conn, settings):
        targets = _targets_by_id(store.list_items(conn), store.list_series(conn), settings, now())
        order = list(KIND_NAMES)
        rules = [c for c in store.list_constraints(conn) if c.kind in KIND_NAMES]
        rules.sort(key=lambda c: order.index(c.kind))  # stable: the order added within a kind
        return [_rule_out(c, store.constraint_source(conn, c.id), targets) for c in rules]


@app.get("/api/rules/targets")
def list_targets() -> list[TargetOut]:
    """What a rule can name: series first, then one-off items with work or blocks from this week on, each by title.

    Items a rule already names are always listed, so editing that rule shows them.
    """
    with database() as (conn, settings):
        moment = now()
        items = store.list_items(conn)
        targets = _targets_by_id(items, store.list_series(conn), settings, moment)
        this_week = local_monday(moment, settings.timezone)
        named = {i for c in store.list_constraints(conn) for i in c.params.get("item_ids", [])}
        named_series = {i for c in store.list_constraints(conn) for i in c.params.get("series_ids", [])}
        today = moment.astimezone(ZoneInfo(settings.timezone)).date()
        ended = {s.id for s in store.list_series(conn) if s.end_date is not None and s.end_date < today}
        ends: dict[UUID, datetime] = {}
        for b in store.list_blocks(conn):
            ends[b.item_id] = max(ends.get(b.item_id, b.end), b.end)
        week_start = week_horizon(this_week, settings.timezone).start
        current = {
            i.id
            for i in items
            if i.series_id is None
            and (
                i.id in named
                or any(w >= this_week for w in weeks_touched(i, settings.timezone, moment))
                or ends.get(i.id, week_start) > week_start
            )
        }
        series = sorted(
            (t for t in targets.values() if t.kind == "series" and (t.id not in ended or t.id in named_series)),
            key=lambda t: t.title.lower(),
        )
        one_offs = sorted((targets[i] for i in current), key=lambda t: t.title.lower())
        return series + one_offs


@app.post("/api/rules", status_code=201)
def add_rule(request: RuleIn, week: date) -> WeekOut:
    """Add a rule, re-plan every planned week from this one on, and return the viewed `week`."""
    with database() as (conn, settings):
        rule = _to_rule(conn, request, settings)

        def change(trial: sqlite3.Connection) -> None:
            store.put_constraint(trial, rule)
            _free_covered(trial, [rule], settings)

        return _change_everywhere(conn, settings, change, week, f"rule {rule.kind}")


@app.put("/api/rules/{rule_id}")
def update_rule(rule_id: UUID, request: RuleIn, week: date) -> WeekOut:
    """Change a rule, keeping its kind, weight and source; re-plan and return the viewed `week`."""
    with database() as (conn, settings):
        old = next((c for c in store.list_constraints(conn) if c.id == rule_id), None)
        if old is None:
            raise HTTPException(status_code=404, detail=RULE_GONE)
        if old.kind != request.kind:
            raise HTTPException(status_code=422, detail=KIND_FIXED)
        rule = replace(_to_rule(conn, request, settings), id=old.id, weight=old.weight)

        def change(trial: sqlite3.Connection) -> None:
            store.put_constraint(trial, rule)
            _free_covered(trial, [old, rule], settings)

        return _change_everywhere(conn, settings, change, week, f"rule {rule.kind}")


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: UUID, week: date) -> WeekOut:
    """Delete a rule, re-plan, and return the viewed `week`."""
    with database() as (conn, settings):
        old = next((c for c in store.list_constraints(conn) if c.id == rule_id), None)
        if old is None:
            raise HTTPException(status_code=404, detail=RULE_GONE)

        def change(trial: sqlite3.Connection) -> None:
            store.delete_constraint(trial, rule_id)
            _free_covered(trial, [old], settings)

        return _change_everywhere(conn, settings, change, week, f"rule {old.kind}")


def _to_rule(conn: sqlite3.Connection, request: RuleIn, settings: SolverSettings) -> Constraint:
    """The dialog's fields as a Constraint, stored the way week files store it, or a 422 with the dialog's message."""
    if request.kind == "daily_limit":
        if request.every_item is False and (request.item_ids or request.series_ids):
            raise HTTPException(status_code=422, detail="A daily limit counts the whole day, so it names no items.")
        return Constraint("daily_limit", {"max_min": _limit_min(request.max_min, settings), "weekdays": _days(request.weekdays)}, hard=True)

    params: dict[str, Any] = {}
    if request.kind == "time_preference":
        if not request.ranges:
            raise HTTPException(status_code=422, detail="Add at least one range of times.")
        if len(request.ranges) > MAX_RANGES:
            raise HTTPException(status_code=422, detail=f"Use at most {MAX_RANGES} ranges.")
        ranges = []
        for r in request.ranges:
            if r.start_time == r.end_time:
                raise HTTPException(status_code=422, detail="Start and end can't be the same time.")
            ranges.append({"weekdays": _days(r.weekdays), "start_time": r.start_time, "end_time": r.end_time})
        params = {"mode": request.mode, "ranges": ranges}
    else:
        gap = request.min_gap_days
        if gap is None or not 1 <= gap <= 6:
            raise HTTPException(status_code=422, detail="Use a whole number of days from 1 to 6.")
        params = {"min_gap_days": gap}

    if not request.every_item:
        if not request.item_ids and not request.series_ids:
            raise HTTPException(status_code=422, detail=PICK_TARGETS)
        items = store.list_items(conn)
        series_ids = {i.series_id for i in items} | {s.id for s in store.list_series(conn)}
        if set(request.item_ids) - {i.id for i in items} or set(request.series_ids) - series_ids:
            raise HTTPException(status_code=422, detail="One of the picked items no longer exists. Pick again.")
        if request.item_ids:
            params["item_ids"] = list(dict.fromkeys(request.item_ids))
        if request.series_ids:
            params["series_ids"] = list(dict.fromkeys(request.series_ids))
    return Constraint(request.kind, params)


def _free_covered(conn: sqlite3.Connection, rules: list[Constraint], settings: SolverSettings) -> None:
    """Drop the planned sessions ahead of the items soft rules cover, so they are placed again under the change.

    Stability is the top score tier, so without this a new wish would never
    move work that is already planned. Hard rules (daily limits) leave the
    plan alone: they move only what they must, like a work frame. Done,
    started and locked sessions stay.
    """
    soft = [r for r in rules if r.kind in ("time_preference", "rest_between")]
    if not soft:
        return
    items = store.list_items(conn)
    covered: set[UUID] = set()
    for rule in soft:
        item_ids, series_ids = set(rule.params.get("item_ids", [])), set(rule.params.get("series_ids", []))
        every = not item_ids and not series_ids
        covered |= {i.id for i in items if every or i.id in item_ids or (i.series_id is not None and i.series_id in series_ids)}
    open_from = open_from_moment(now(), settings.slot_min)
    store.delete_blocks(
        conn,
        [
            b.id
            for b in store.list_blocks(conn)
            if b.item_id in covered and b.status is BlockStatus.PLANNED and not b.locked and b.start >= open_from
        ],
    )


def _days(weekdays: list[int] | None) -> list[int]:
    if not weekdays or any(day not in range(7) for day in weekdays):
        raise HTTPException(status_code=422, detail="Pick at least one day.")
    return sorted(set(weekdays))


def _limit_min(max_min: int | None, settings: SolverSettings) -> int:
    """A daily limit's minutes, rounded down to the slot grid like the dialog's "Planned as"."""
    if max_min is None or max_min <= 0:
        raise HTTPException(status_code=422, detail="Use a length longer than 0m.")
    if max_min > 24 * 60:
        raise HTTPException(status_code=422, detail="A day only has 24h.")
    return planned_down(max_min, settings.slot_min)


def _targets_by_id(
    items: list[Item], series: list[Series], settings: SolverSettings, moment: datetime
) -> dict[UUID, TargetOut]:
    """Every item and series a rule could name, by id. A series takes its latest occurrence's title."""
    targets: dict[UUID, TargetOut] = {}
    latest: dict[UUID, date] = {}
    for item in items:
        if item.series_id is not None and item.occurrence_date is not None:
            if item.occurrence_date >= latest.get(item.series_id, item.occurrence_date):
                latest[item.series_id] = item.occurrence_date
                targets[item.series_id] = TargetOut(id=item.series_id, kind="series", title=item.title)
        else:
            week = due_week(item, settings.timezone) or next(iter(weeks_touched(item, settings.timezone, moment)), None)
            targets[item.id] = TargetOut(id=item.id, kind="item", title=item.title, week_start=week)
    for one in series:  # a stored series goes by its own title, and counts before it has occurrences
        targets[one.id] = TargetOut(id=one.id, kind="series", title=one.title)
    return targets


def _rule_out(rule: Constraint, source: str | None, targets: dict[UUID, TargetOut]) -> RuleOut:
    """A stored rule in the dialog's terms. A single top-level range (week files allow it) becomes `ranges`."""
    params = rule.params
    ids = [*params.get("item_ids", []), *params.get("series_ids", [])]
    out = RuleOut(
        id=rule.id,
        kind=rule.kind,  # type: ignore[arg-type]
        source=source,
        every_item=rule.kind != "daily_limit" and not ids,
        targets=[targets[i] for i in ids if i in targets],
    )
    if rule.kind == "daily_limit":
        out.max_min = params.get("max_min")
        out.weekdays = sorted(params.get("weekdays", range(7)))
    elif rule.kind == "time_preference":
        raw = params.get("ranges") or [{k: params[k] for k in ("weekdays", "start_time", "end_time") if k in params}]
        out.mode = params.get("mode", "prefer")
        out.ranges = [RangeIn(**r) for r in raw]
    else:
        out.min_gap_days = params.get("min_gap_days", 1)
    return out


def _change_everywhere(
    conn: sqlite3.Connection,
    settings: SolverSettings,
    change: Callable[[sqlite3.Connection], None],
    week: date,
    log_name: str,
) -> WeekOut:
    """Apply a change that reaches every week (a work frame or a rule), all or nothing, and return the viewed week."""
    moment = now()
    first, last = _weeks_from_now(conn, settings, moment)
    _change_and_plan(
        conn,
        settings,
        change,
        first,
        last,
        moment,
        log_name=log_name,
        timed_out=CHANGE_TIMED_OUT,
        broke=weeks_would_break,
        clear_plans=True,
    )
    log.info("changed %s, re-planned %s to %s", log_name, first, last)
    return week_out(conn, settings, week, _status_or_stored(conn, settings, week, moment), moment)


def _weeks_from_now(conn: sqlite3.Connection, settings: SolverSettings, moment: datetime) -> tuple[date, date]:
    """This week through the last week that has a plan or planned blocks, and at least the planning span."""
    first = local_monday(moment, settings.timezone)
    open_from = open_from_moment(moment, settings.slot_min)
    ahead = [b for b in store.list_blocks(conn) if b.status is BlockStatus.PLANNED and b.start >= open_from]
    later = store.planned_weeks(conn) + weeks_of_blocks(ahead, settings.timezone)
    return first, max([first + (MAX_SPAN_WEEKS - 1) * ONE_WEEK, *later])


def _put_and_plan(
    conn: sqlite3.Connection,
    settings: SolverSettings,
    item: Item,
    first: date,
    last: date,
    moment: datetime,
    timed_out: str,
    accept_shortfall: bool = False,
) -> None:
    """Store the item (new or changed) and re-plan [first..last], or raise HTTPException and change nothing.

    Kept only if no week that fit before stops fitting and all of the item's work is placed.
    An "N times a week" item it leaves with fewer sessions needs accept_shortfall (else 409).
    """
    before = _shortfalls(conn, settings, moment)

    def all_placed(trial: sqlite3.Connection, after: dict[date, bool]) -> None:
        _confirm_shortfalls(trial, settings, moment, before, accept_shortfall, {item.id})
        trial_blocks = store.list_blocks(trial)
        placed = effective_item(item, trial_blocks, store.list_work_frames(trial), settings, moment)
        if remaining_min(placed, trial_blocks) > 0:
            # Its work could only go into weeks that can't be planned.
            broken = [week for week, fit in sorted(after.items()) if not fit]
            raise HTTPException(status_code=422, detail=waits_on_broken_week(broken) if broken else DOES_NOT_FIT)

    _change_and_plan(
        conn,
        settings,
        lambda trial: store.put_item(trial, item),
        first,
        last,
        moment,
        log_name=repr(item.title),
        timed_out=timed_out,
        broke=lambda _weeks: DOES_NOT_FIT,
        check=all_placed,
    )


def _change_and_plan(
    conn: sqlite3.Connection,
    settings: SolverSettings,
    change: Callable[[sqlite3.Connection], None],
    first: date,
    last: date,
    moment: datetime,
    *,
    log_name: str,
    timed_out: str,
    broke: Callable[[list[date]], str],
    check: Callable[[sqlite3.Connection, dict[date, bool]], None] | None = None,
    clear_plans: bool = False,
) -> None:
    """Apply `change` and re-plan [first..last], or raise HTTPException and change nothing.

    Tried on an in-memory copy. It is kept only if no week that fit before
    stops fitting (else 422 with `broke(weeks)`) and `check`, if given, raises
    nothing. With `clear_plans`, every week's plan mark is cleared after the
    change, so weeks outside the span re-plan when next viewed.
    """
    trial = store.copy_in_memory(conn)
    try:
        before = _baseline(trial, settings, first, last, moment)
        change(trial)
        if clear_plans:
            store.clear_plans(trial)
        after = plan_weeks(trial, settings, first, last, moment)
        if broken := [week for week, fit in sorted(after.items()) if before.get(week) and not fit]:
            raise HTTPException(status_code=422, detail=broke(broken))
        if check is not None:
            check(trial, after)
        store.keep_copy(trial, conn)
    except PlannerTimeout as error:
        log.warning("saving %s: %s", log_name, error)
        raise HTTPException(status_code=503, detail=timed_out) from error
    finally:
        trial.close()


def _edited(old: Item, new: Item) -> Item:
    """The changed item: the dialog's fields from `new`, everything the dialog doesn't show from `old`.

    Check-in and If missed come from `new`; the caller keeps the old ones when the request left them out.

    A deadline is the dialog's for "before a deadline". On other presets the
    dialog has no deadline field, so an imported item's deadline is kept, unless
    it came from the "before a deadline" preset being changed away.
    """
    if new.flex_preset is FlexPreset.BEFORE_DEADLINE:
        deadline = new.deadline
    else:
        deadline = None if old.flex_preset is FlexPreset.BEFORE_DEADLINE else old.deadline
    return replace(
        new,
        id=old.id,
        deadline=deadline,
        parent_id=old.parent_id,
        depends_on=old.depends_on,
        catch_up_of=old.catch_up_of,
        series_id=old.series_id,
        occurrence_date=old.occurrence_date,
    )


def _when(form: ItemIn | ItemFormOut) -> tuple[Any, ...]:
    """The fields that say when an item can go. The week only counts for items that belong to one."""
    week = form.week_start if form.preset in ("days", "every_day") else None
    weekdays = sorted(set(form.weekdays or [])) if form.preset in ("days", "every_day") else None
    return (form.preset, week, form.day, form.start_time, form.end_time, weekdays, form.deadline_date, form.deadline_time)


def _status(conn: sqlite3.Connection, settings: SolverSettings, week_start: date, moment: datetime) -> bool:
    """The week's plan status, planning it (and the weeks its deadline items reach) first if it has none."""
    feasible = store.plan_status(conn, week_start)
    if feasible is None:
        # Occurrences first, so a repeating deadline item due next week can stretch the span.
        create_occurrences(conn, settings, week_start, week_start + (MAX_SPAN_WEEKS - 1) * ONE_WEEK, moment)
        first, last = span_for_view(conn, settings, week_start, moment)
        began = perf_counter()
        outcome = plan_weeks(conn, settings, first, last, moment)
        feasible = outcome[week_start]
        broken = [str(w) for w, fit in outcome.items() if not fit]
        log.info("%s to %s planned in %.2fs%s", first, last, perf_counter() - began, f", can't plan {broken}" if broken else "")
    return feasible


def _status_or_stored(conn: sqlite3.Connection, settings: SolverSettings, week_start: date, moment: datetime) -> bool:
    """Like _status, but after a change that already happened: a timeout shows the week's last stored plan."""
    try:
        return _status(conn, settings, week_start, moment)
    except PlannerTimeout as error:
        log.warning("%s: %s", week_start, error)
        return store.plan_status(conn, week_start) is not False


def _baseline(conn: sqlite3.Connection, settings: SolverSettings, first: date, last: date, moment: datetime) -> dict[date, bool]:
    """Whether each week in the span fit before an item was added: its stored status, or a plan without the item."""
    weeks = [first + timedelta(weeks=n) for n in range((last - first).days // 7 + 1)]
    stored = {week: store.plan_status(conn, week) for week in weeks}
    if all(status is not None for status in stored.values()):
        return {week: bool(status) for week, status in stored.items()}
    return plan_weeks(conn, settings, first, last, moment)


def to_item(request: ItemIn, settings: SolverSettings, moment: datetime, check_past: bool = True) -> Item:
    """Turn the dialog's local fields into an Item in UTC. Raises Invalid with a message for the dialog.

    With check_past false, a time, deadline or week that has already passed is
    allowed: editing a past item without changing when it is.
    """
    zone = ZoneInfo(settings.timezone)

    def at(day: date, clock: time) -> datetime:
        return datetime.combine(day, clock, tzinfo=zone).astimezone(UTC)

    title = request.title.strip()
    if not title:
        raise Invalid("Give the item a title.")
    if request.preset == "every_day":
        return _every_day_item(request, title, _days_params(request, at, moment, check_past))
    preset = FlexPreset(request.preset)
    exact = preset is FlexPreset.EXACT
    if exact and (request.estimate_min is not None or request.max_chunk_min is not None):
        raise Invalid("An exact-time item takes its length from its start and end, so it has no estimate.")
    if not exact and (request.estimate_min is None or request.estimate_min <= 0):
        raise Invalid("Add an estimate, like 45m or 1h 30m.")
    if request.max_chunk_min is not None and request.max_chunk_min <= 0:
        raise Invalid("Use a session length like 45m or 1h 30m.")

    params: dict[str, Any] = {}
    deadline = None
    if preset in (FlexPreset.EXACT, FlexPreset.DAY, FlexPreset.DAY_RANGE):
        day = _need(request.day, "Pick a date.")
        ends = at(day + timedelta(days=1), time())  # the end of that day
        if preset is FlexPreset.DAY:
            params = {"day": day}
        else:
            start, end = _time_pair(request)
            if start is None or end is None:
                raise Invalid("Give a start and an end time.")
            ends = at(day + timedelta(days=1 if end <= start else 0), end)  # end before start: the next day
            if exact:
                params = {"start": at(day, start), "end": ends}
            else:
                params = {"day": day, "start_time": start, "end_time": end}
        if check_past and ends <= moment:
            raise Invalid("That time has already passed.")
    elif preset is FlexPreset.DAYS:
        params = _days_params(request, at, moment, check_past)
    else:
        due_day = _need(request.deadline_date, "Pick a due date.")
        deadline = at(due_day, _need(request.deadline_time, "Pick a due time."))
        if check_past and deadline <= moment:
            raise Invalid("That deadline has already passed.")

    checkable, on_miss = _check_in_fields(request, exact)
    return Item(
        title=title,
        flex_preset=preset,
        preset_params=params,
        estimate_min=request.estimate_min,
        deadline=deadline,
        max_chunk_min=request.max_chunk_min,
        one_block_per_day=request.one_block_per_day,
        checkable=checkable,
        on_miss=on_miss,
    )


def _check_in_fields(request: ItemIn, exact: bool) -> tuple[bool, OnMiss]:
    """Whether it asks for check-ins and what a miss does, with the defaults for its preset."""
    checkable = request.checkable if request.checkable is not None else not exact
    default = OnMiss.SKIP if exact else OnMiss.RESCHEDULE
    on_miss = OnMiss(request.on_miss) if request.on_miss is not None else default
    if exact and on_miss is OnMiss.RESCHEDULE:
        raise Invalid("An exact-time item can't move, so pick Catch up, Skip or Ask me if it's missed.")
    return checkable, on_miss


def _days_params(
    request: ItemIn, at: Callable[[date, time], datetime], moment: datetime, check_past: bool = True
) -> dict[str, Any]:
    """preset_params for an item on chosen days of the viewed week."""
    weekdays = sorted(set(request.weekdays or []))
    if not weekdays or any(d not in range(7) for d in weekdays):
        raise Invalid("Pick at least one day.")
    if request.week_start.weekday() != 0:
        raise Invalid("week_start must be a Monday.")
    params: dict[str, Any] = {"week": request.week_start, "weekdays": weekdays}
    start, end = _time_pair(request)
    if start is not None and end is not None:
        params |= {"start_time": start, "end_time": end}
    if check_past and at(request.week_start + timedelta(days=7), time()) <= moment:
        raise Invalid("That week has already passed.")
    return params


def _every_day_item(request: ItemIn, title: str, params: dict[str, Any]) -> Item:
    """One session of session_min on each chosen day. Weekdays are kept as picked; the planner
    works out which are still open and rounds the session to the slot grid (effective_item)."""
    if request.estimate_min is not None or request.max_chunk_min is not None:
        raise Invalid("An every-day item takes its length from Each day, so it has no estimate or longest session.")
    session = _need(request.session_min, "Add a length for each day, like 30m or 1h.")
    if session <= 0:
        raise Invalid("Use a length like 30m or 1h.")
    checkable, on_miss = _check_in_fields(request, exact=False)
    return Item(
        title=title,
        flex_preset=FlexPreset.DAYS,
        preset_params=params | {"every_day": True, "session_min": session},
        estimate_min=session * len(params["weekdays"]),
        max_chunk_min=session,
        one_block_per_day=True,
        checkable=checkable,
        on_miss=on_miss,
    )


def editable(item: Item) -> bool:
    """Whether the edit dialog can show and change the item: not Custom, and with the fields its preset needs."""
    preset = item.flex_preset
    if preset is FlexPreset.CUSTOM or (preset is FlexPreset.BEFORE_DEADLINE and item.deadline is None):
        return False
    every_day = preset is FlexPreset.DAYS and every_day_session(item.preset_params) is not None
    return preset is FlexPreset.EXACT or every_day or item.estimate_min is not None


def from_item(item: Item, source: str | None, settings: SolverSettings) -> ItemFormOut:
    """The item in the dialog's terms: the inverse of to_item. Local dates and times are in my timezone."""
    zone = ZoneInfo(settings.timezone)
    params = item.preset_params
    fields: dict[str, Any] = {
        "id": item.id,
        "source": source,
        "editable": editable(item),
        "series_id": item.series_id,
        "title": item.title,
        "estimate_min": item.estimate_min,
        "max_chunk_min": item.max_chunk_min,
        "one_block_per_day": item.one_block_per_day,
        "checkable": item.checkable,
        "on_miss": item.on_miss.value,
    }
    preset = item.flex_preset
    if preset is FlexPreset.EXACT:
        start, end = params["start"].astimezone(zone), params["end"].astimezone(zone)
        fields |= {"preset": "exact", "day": start.date(), "start_time": start.time(), "end_time": end.time()}
        fields["week_start"] = monday(start.date())
    elif preset in (FlexPreset.DAY, FlexPreset.DAY_RANGE):
        fields |= {"preset": preset.value, "day": params["day"], "week_start": monday(params["day"])}
        if preset is FlexPreset.DAY_RANGE:
            fields |= {"start_time": params["start_time"], "end_time": params["end_time"]}
    elif preset is FlexPreset.DAYS:
        fields |= {"preset": "days", "week_start": params["week"], "weekdays": list(params["weekdays"])}
        fields |= {"start_time": params.get("start_time"), "end_time": params.get("end_time")}
        if (session := every_day_session(params)) is not None:
            fields |= {"preset": "every_day", "session_min": session, "estimate_min": None, "max_chunk_min": None}
            fields["one_block_per_day"] = False  # every-day items set it themselves
    elif preset is FlexPreset.BEFORE_DEADLINE and item.deadline is not None:
        due = item.deadline.astimezone(zone)
        fields |= {"preset": "before_deadline", "deadline_date": due.date(), "deadline_time": due.time()}
        fields["week_start"] = monday(due.date())
    else:  # Custom, or a deadline preset with no deadline: not editable in the dialog
        fields |= {"preset": "custom", "week_start": monday(now().astimezone(zone).date())}
    return ItemFormOut(**fields)


def _need(value: Any, message: str) -> Any:
    if value is None:
        raise Invalid(message)
    return value


def _time_pair(request: ItemIn) -> tuple[time | None, time | None]:
    """Start and end times: both or neither, and not the same time."""
    start, end = request.start_time, request.end_time
    if (start is None) != (end is None):
        raise Invalid("Give both a start and an end time, or neither.")
    if start is not None and start == end:
        raise Invalid("The start and end times are the same.")
    return start, end


def week_out(
    conn: sqlite3.Connection, settings: SolverSettings, week_start: date, feasible: bool, moment: datetime
) -> WeekOut:
    """The week's stored blocks and frames as a response. Estimates are the work items have as of `moment`."""
    week = week_horizon(week_start, settings.timezone)
    blocks = store.list_blocks(conn, week.start, week.end) if feasible else []
    waiting = waiting_on_broken_weeks(conn, settings, week_start, moment)
    # Sessions are counted across every week, so look at all blocks, in start order.
    every_block = store.list_blocks(conn)
    frames = store.list_work_frames(conn)
    items = {item.id: item for item in effective_items(store.list_items(conn), every_block, frames, settings, moment)}
    sessions: dict[UUID, list[UUID]] = {}
    for b in every_block:
        sessions.setdefault(b.item_id, []).append(b.id)
    placed = {item_id: placed_min(items[item_id], every_block) for item_id in sessions}
    stored_series = {s.id: s for s in store.list_series(conn)}
    acks = store.shortfall_acks(conn)
    history = _with_history(every_block)
    in_week = {items[b.item_id].series_id for b in blocks} | {i.series_id for i in items.values() if i.id in waiting}
    return WeekOut(
        week_start=week_start,
        timezone=settings.timezone,
        slot_min=settings.slot_min,
        feasible=feasible,
        blocks=[
            BlockOut(
                id=b.id,
                item_id=b.item_id,
                title=items[b.item_id].title,
                start=b.start,
                end=b.end,
                fixed=items[b.item_id].flex_preset is FlexPreset.EXACT,
                session=sessions[b.item_id].index(b.id) + 1,
                sessions=len(sessions[b.item_id]),
                placed_min=placed[b.item_id],
                estimate_min=items[b.item_id].estimate_min,
                editable=editable(items[b.item_id]),
                series_id=_stored(items[b.item_id].series_id, stored_series),
                checkable=items[b.item_id].checkable,
                status=b.status.value,
                done_min=b.actual_min if b.status in (BlockStatus.DONE, BlockStatus.PARTIAL) else None,
                missed_action=None if b.missed_action is None else b.missed_action.value,
                history=b.item_id in history,
                on_miss=checkins.policy_for(items[b.item_id]).value,
            )
            for b in blocks
        ],
        frames=[
            SpanOut(start=w.start, end=w.end)
            for w in frame_spans(frames, week_start, settings.timezone)
        ],
        # Items that can't be placed: a custom preset with no windows painted yet, and
        # items whose work waits on a week that can't be planned (with the reason).
        unscheduled=[
            ItemRef(
                id=i.id,
                title=i.title,
                estimate_min=i.estimate_min,
                reason=waiting.get(i.id),
                sessions=len(sessions.get(i.id, [])),
                editable=editable(i),
                series_id=_stored(i.series_id, stored_series),
                history=i.id in history,
            )
            for i in items.values()
            if (i.flex_preset is FlexPreset.CUSTOM and not i.preset_params.get("windows")) or i.id in waiting
        ],
        series=[repeat_out(s) for s in stored_series.values() if s.id in in_week],
        shortfalls=[
            ShortfallOut(
                item_id=s.item_id,
                title=s.title,
                sessions=s.sessions,
                gets=s.gets,
                message=shortfall_message(s, settings, moment),
            )
            for s in _shortfalls(conn, settings, moment)
            if s.week == week_start and s.gets < acks.get(s.item_id, s.sessions)
        ],
    )


def _stored(series_id: UUID | None, stored: dict[UUID, Series]) -> UUID | None:
    """The series id, if that series is stored (occurrences imported before series were stored have none)."""
    return series_id if series_id in stored else None


def main() -> None:
    """Run the API on this machine only, reloading on code changes."""
    import uvicorn

    uvicorn.run("mycal.api:app", host="127.0.0.1", port=8000, reload=True)
