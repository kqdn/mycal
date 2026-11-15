"""The week API: serve a week's stored plan as JSON (Milestone 3).

Not part of the solver: like demo.py and store.py, this module is a caller.
It reads the database and serves HTTP; planning goes through planner.py,
which calls solve(). The core modules never import it.

A week is planned the first time it is viewed and the plan is stored, so
later views are instant and the plan survives restarts. A week re-plans when
its plan is cleared (an import clears every week's plan), and adding or
deleting an item re-plans the weeks it touches right away.

Adding an item is all or nothing: the change is tried on an in-memory copy
of the database, and only kept if it doesn't break a week that fit before.
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
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mycal import store
from mycal.model import FlexPreset, Item
from mycal.planner import frame_spans, plan_week, replan, week_horizon, weeks_of_blocks, weeks_touched
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


class SpanOut(BaseModel):
    start: datetime
    end: datetime


class ItemRef(BaseModel):
    id: UUID
    title: str
    estimate_min: int | None  # None when the item has no estimate


class WeekOut(BaseModel):
    week_start: date
    timezone: str
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
        feasible = store.plan_status(conn, week_start)
        if feasible is None:
            began = perf_counter()
            result = plan_week(conn, settings, week_start, now())
            feasible = result.feasible
            log.info("%s planned in %.2fs, %s", week_start, perf_counter() - began, result.status)
        return week_out(conn, settings, week_start, feasible)


class ItemIn(BaseModel):
    """A new item as the New item dialog collects it: local dates and times in my timezone.

    `week_start` is the week being viewed (its Monday). A "days" item belongs to it,
    and it is the week the response shows.
    """

    week_start: date
    title: str
    preset: Literal["exact", "day", "day_range", "days", "before_deadline"]
    day: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    weekdays: list[int] | None = None
    deadline_date: date | None = None
    deadline_time: time | None = None
    estimate_min: int | None = None
    max_chunk_min: int | None = None
    one_block_per_day: bool = False


class Invalid(ValueError):
    """A request the dialog should explain in words; it becomes a 422 with that message."""


DOES_NOT_FIT = (
    "It doesn't fit: there isn't enough free time in its days and work frames. "
    "Try more days, a later deadline or a smaller estimate."
)


@app.post("/api/items", status_code=201)
def add_item(request: ItemIn) -> WeekOut:
    """Add an item, re-plan the weeks it touches and return the viewed week. 422 if it doesn't fit."""
    with database() as (conn, settings):
        moment = now()
        try:
            item = to_item(request, settings, moment)
        except Invalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        weeks = sorted(set(weeks_touched(item, settings.timezone, moment)))
        trial = store.copy_in_memory(conn)
        try:
            fit_before = {week: _feasible(trial, settings, week, moment) for week in weeks}
            store.put_item(trial, item)
            results = replan(trial, settings, weeks, moment)
            if any(fit_before[week] and not result.feasible for week, result in results.items()):
                raise HTTPException(status_code=422, detail=DOES_NOT_FIT)
            store.keep_copy(trial, conn)
        finally:
            trial.close()
        log.info("added %r, re-planned %s", item.title, ", ".join(str(w) for w in results) or "no weeks")
        return week_out(conn, settings, request.week_start, _feasible(conn, settings, request.week_start, moment))


@app.delete("/api/items/{item_id}")
def delete_item(item_id: UUID, week: date) -> WeekOut:
    """Delete an item and its blocks, re-plan the weeks they were in, and return the viewed `week`."""
    with database() as (conn, settings):
        if store.get_item(conn, item_id) is None:
            raise HTTPException(status_code=404, detail="That item no longer exists.")
        moment = now()
        weeks = weeks_of_blocks([b for b in store.list_blocks(conn) if b.item_id == item_id], settings.timezone)
        store.delete_item(conn, item_id)
        replan(conn, settings, weeks, moment)
        return week_out(conn, settings, week, _feasible(conn, settings, week, moment))


def _feasible(conn: sqlite3.Connection, settings: SolverSettings, week_start: date, moment: datetime) -> bool:
    """The viewed week's plan status, planning it first if it has none."""
    feasible = store.plan_status(conn, week_start)
    return plan_week(conn, settings, week_start, moment).feasible if feasible is None else feasible


def to_item(request: ItemIn, settings: SolverSettings, moment: datetime) -> Item:
    """Turn the dialog's local fields into an Item in UTC. Raises Invalid with a message for the dialog."""
    zone = ZoneInfo(settings.timezone)

    def at(day: date, clock: time) -> datetime:
        return datetime.combine(day, clock, tzinfo=zone).astimezone(UTC)

    title = request.title.strip()
    if not title:
        raise Invalid("Give the item a title.")
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
        if ends <= moment:
            raise Invalid("That time has already passed.")
    elif preset is FlexPreset.DAYS:
        weekdays = sorted(set(request.weekdays or []))
        if not weekdays or any(d not in range(7) for d in weekdays):
            raise Invalid("Pick at least one day.")
        if request.week_start.weekday() != 0:
            raise Invalid("week_start must be a Monday.")
        params = {"week": request.week_start, "weekdays": weekdays}
        start, end = _time_pair(request)
        if start is not None and end is not None:
            params |= {"start_time": start, "end_time": end}
        if at(request.week_start + timedelta(days=7), time()) <= moment:
            raise Invalid("That week has already passed.")
    else:
        due_day = _need(request.deadline_date, "Pick a due date.")
        deadline = at(due_day, _need(request.deadline_time, "Pick a due time."))
        if deadline <= moment:
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


def week_out(conn: sqlite3.Connection, settings: SolverSettings, week_start: date, feasible: bool) -> WeekOut:
    """The week's stored blocks and frames as a response."""
    week = week_horizon(week_start, settings.timezone)
    items = {item.id: item for item in store.list_items(conn)}
    blocks = store.list_blocks(conn, week.start, week.end) if feasible else []
    return WeekOut(
        week_start=week_start,
        timezone=settings.timezone,
        feasible=feasible,
        blocks=[
            BlockOut(
                id=b.id,
                item_id=b.item_id,
                title=items[b.item_id].title,
                start=b.start,
                end=b.end,
                fixed=items[b.item_id].flex_preset is FlexPreset.EXACT,
            )
            for b in blocks
        ],
        frames=[
            SpanOut(start=w.start, end=w.end)
            for w in frame_spans(store.list_work_frames(conn), week_start, settings.timezone)
        ],
        # Items that can never be placed: a custom preset with no windows painted yet.
        unscheduled=[
            ItemRef(id=i.id, title=i.title, estimate_min=i.estimate_min)
            for i in items.values()
            if i.flex_preset is FlexPreset.CUSTOM and not i.preset_params.get("windows")
        ],
    )


def main() -> None:
    """Run the API on this machine only, reloading on code changes."""
    import uvicorn

    uvicorn.run("mycal.api:app", host="127.0.0.1", port=8000, reload=True)
