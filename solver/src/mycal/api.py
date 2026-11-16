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

from mycal import store
from mycal.model import BlockStatus, FlexPreset, Item
from mycal.presets import every_day_session
from mycal.planner import (
    effective_item,
    effective_items,
    frame_spans,
    monday,
    open_from_moment,
    plan_weeks,
    remaining_min,
    span_for_item,
    PlannerTimeout,
    placed_min,
    span_for_view,
    waiting_on_broken_weeks,
    week_horizon,
    week_title,
    weeks_of_blocks,
    weeks_touched,
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


class SpanOut(BaseModel):
    start: datetime
    end: datetime


class ItemRef(BaseModel):
    id: UUID
    title: str
    estimate_min: int | None  # None when the item has no estimate
    reason: str | None = None  # why it isn't scheduled, when it is waiting on a week that can't be planned
    sessions: int = 0  # how many blocks it has in every week


class WeekOut(BaseModel):
    week_start: date
    timezone: str
    slot_min: int  # so the page can show planned lengths without hardcoding 15
    feasible: bool
    blocks: list[BlockOut]
    frames: list[SpanOut]  # work-frame time inside the week, merged
    unscheduled: list[ItemRef]


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


class ItemFormOut(BaseModel):
    """A stored item in the dialog's terms, to fill in the edit dialog. Lengths are as typed, not rounded.

    `week_start` is the item's own week for "days" and "every_day" items (send it
    back as is). `editable` is false for Custom items, which the dialog can't show.
    """

    id: UUID
    source: str | None  # the week file it was imported from, or None if added in the app
    editable: bool
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
        _put_and_plan(conn, settings, item, first, last, moment, ADD_TIMED_OUT)
        log.info("added %r, re-planned %s to %s", item.title, first, last)
        return week_out(conn, settings, request.week_start, _status_or_stored(conn, settings, request.week_start, moment), moment)


@app.delete("/api/items/{item_id}")
def delete_item(item_id: UUID, week: date) -> WeekOut:
    """Delete an item and its blocks, re-plan the weeks they were in, and return the viewed `week`."""
    with database() as (conn, settings):
        if store.get_item(conn, item_id) is None:
            raise HTTPException(status_code=404, detail=ITEM_GONE)
        moment = now()
        weeks = weeks_of_blocks([b for b in store.list_blocks(conn) if b.item_id == item_id], settings.timezone)
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
    nothing changes. Fields the dialog doesn't show (dependencies, checkable,
    on_miss, parent, series, source) are kept. Sessions that already started
    or are done stay and count toward the work.
    """
    with database() as (conn, settings):
        old = store.get_item(conn, item_id)
        if old is None:
            raise HTTPException(status_code=404, detail=ITEM_GONE)
        if old.flex_preset is FlexPreset.CUSTOM:
            raise HTTPException(status_code=422, detail=CUSTOM_NOT_EDITABLE)
        moment = now()
        blocks = [b for b in store.list_blocks(conn) if b.item_id == item_id]
        moved = _when(request) != _when(from_item(old, None, settings))
        try:
            # A changed time must still lie ahead; an unchanged one may have passed (fix a past item's title).
            new = _edited(old, to_item(request, settings, moment, check_past=moved))
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
            _put_and_plan(conn, settings, new, min(weeks), max(weeks), moment, EDIT_TIMED_OUT)
        else:
            store.put_item(conn, new)  # nothing left to place, say a past item's new title
        log.info("edited %r, re-planned %s", new.title, f"{min(weeks)} to {max(weeks)}" if weeks else "nothing")
        return week_out(conn, settings, week, _status_or_stored(conn, settings, week, moment), moment)


def _put_and_plan(
    conn: sqlite3.Connection,
    settings: SolverSettings,
    item: Item,
    first: date,
    last: date,
    moment: datetime,
    timed_out: str,
) -> None:
    """Store the item (new or changed) and re-plan [first..last], or raise HTTPException and change nothing.

    Tried on an in-memory copy, kept only if no week that fit before stops
    fitting and all of the item's work is placed.
    """
    trial = store.copy_in_memory(conn)
    try:
        before = _baseline(trial, settings, first, last, moment)
        store.put_item(trial, item)
        after = plan_weeks(trial, settings, first, last, moment)
        if any(before.get(week) and not fit for week, fit in after.items()):
            raise HTTPException(status_code=422, detail=DOES_NOT_FIT)
        trial_blocks = store.list_blocks(trial)
        placed = effective_item(item, trial_blocks, store.list_work_frames(trial), settings, moment)
        if remaining_min(placed, trial_blocks) > 0:
            # Its work could only go into weeks that can't be planned.
            broken = [week for week, fit in sorted(after.items()) if not fit]
            raise HTTPException(status_code=422, detail=waits_on_broken_week(broken) if broken else DOES_NOT_FIT)
        store.keep_copy(trial, conn)
    except PlannerTimeout as error:
        log.warning("saving %r: %s", item.title, error)
        raise HTTPException(status_code=503, detail=timed_out) from error
    finally:
        trial.close()


def _edited(old: Item, new: Item) -> Item:
    """The changed item: the dialog's fields from `new`, everything the dialog doesn't show from `old`.

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
        checkable=old.checkable,
        parent_id=old.parent_id,
        depends_on=old.depends_on,
        on_miss=old.on_miss,
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

    return Item(
        title=title,
        flex_preset=preset,
        preset_params=params,
        estimate_min=request.estimate_min,
        deadline=deadline,
        max_chunk_min=request.max_chunk_min,
        one_block_per_day=request.one_block_per_day,
    )


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
    return Item(
        title=title,
        flex_preset=FlexPreset.DAYS,
        preset_params=params | {"every_day": True, "session_min": session},
        estimate_min=session * len(params["weekdays"]),
        max_chunk_min=session,
        one_block_per_day=True,
    )


def from_item(item: Item, source: str | None, settings: SolverSettings) -> ItemFormOut:
    """The item in the dialog's terms: the inverse of to_item. Local dates and times are in my timezone."""
    zone = ZoneInfo(settings.timezone)
    params = item.preset_params
    fields: dict[str, Any] = {
        "id": item.id,
        "source": source,
        "editable": item.flex_preset is not FlexPreset.CUSTOM,
        "title": item.title,
        "estimate_min": item.estimate_min,
        "max_chunk_min": item.max_chunk_min,
        "one_block_per_day": item.one_block_per_day,
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
        fields |= {"preset": "custom", "editable": False, "week_start": monday(now().astimezone(zone).date())}
    if fields["estimate_min"] is None and preset is not FlexPreset.EXACT and fields["preset"] != "every_day":
        fields["editable"] = False  # the dialog needs an estimate for flexible items
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
            )
            for i in items.values()
            if (i.flex_preset is FlexPreset.CUSTOM and not i.preset_params.get("windows")) or i.id in waiting
        ],
    )


def main() -> None:
    """Run the API on this machine only, reloading on code changes."""
    import uvicorn

    uvicorn.run("mycal.api:app", host="127.0.0.1", port=8000, reload=True)
