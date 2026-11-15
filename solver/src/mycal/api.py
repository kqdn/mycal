"""The week API: serve a week's stored plan as JSON (Milestone 3).

Not part of the solver: like demo.py and store.py, this module is a caller.
It reads the database and serves HTTP; planning goes through planner.py,
which calls solve(). The core modules never import it.

A week is planned the first time it is viewed and the plan is stored, so
later views are instant and the plan survives restarts. A week re-plans when
its plan is cleared (an import clears every week's plan).

All times in responses are UTC. The page converts them to the week's
timezone only for display.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mycal import store
from mycal.model import FlexPreset
from mycal.planner import frame_spans, plan_week, week_horizon
from mycal.settings import SolverSettings

# A child of uvicorn's logger, so lines show in the server console at INFO
# (uvicorn configures its loggers in the worker process, even with reload).
log = logging.getLogger("uvicorn.error.mycal")

# One request plans or writes at a time. The page prefetches neighbor weeks,
# and two requests planning the same week at once would both write a plan.
_lock = threading.Lock()

app = FastAPI(title="mycal")


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
            began = time.perf_counter()
            result = plan_week(conn, settings, week_start, now())
            feasible = result.feasible
            log.info("%s planned in %.2fs, %s", week_start, time.perf_counter() - began, result.status)
        return week_out(conn, settings, week_start, feasible)


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
