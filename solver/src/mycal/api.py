"""Milestone 2 API: load a week file, solve it and return the schedule as JSON.

Not part of the solver: like demo.py, this module is a caller. It reads files
and serves HTTP, then calls solve() through plan_week(). The core modules
never import it.

All times in responses are UTC. The page converts them to the week's
timezone only for display.
"""

from __future__ import annotations

import os
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mycal.demo import Week, load_week, plan_week
from mycal.model import FlexPreset, Window
from mycal.windows import merge_windows, work_frame_windows

WEEKS_DIR_ENV = "MYCAL_WEEKS_DIR"

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


class WeekOut(BaseModel):
    week_start: date
    timezone: str
    feasible: bool
    blocks: list[BlockOut]
    frames: list[SpanOut]  # work-frame time inside the week, merged
    unscheduled: list[ItemRef]


def weeks_dir() -> Path:
    return Path(os.environ.get(WEEKS_DIR_ENV, "weeks"))


@app.get("/api/weeks/{week_start}")
def get_week(week_start: date) -> WeekOut:
    """Solve weeks/<week_start>.toml. A week that cannot be solved still returns 200."""
    path = weeks_dir() / f"{week_start.isoformat()}.toml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No week file for {week_start}")
    try:
        week = load_week(path)
        items, result = plan_week(week)
    except (KeyError, ValueError, tomllib.TOMLDecodeError) as error:
        raise HTTPException(status_code=400, detail=f"Bad week file: {error}") from error

    by_id = {item.id: item for item in items}
    blocks = [
        BlockOut(
            id=b.id,
            item_id=b.item_id,
            title=by_id[b.item_id].title,
            start=b.start,
            end=b.end,
            fixed=by_id[b.item_id].flex_preset is FlexPreset.EXACT,
        )
        for b in result.blocks
    ]
    return WeekOut(
        week_start=week.start,
        timezone=week.settings.timezone,
        feasible=result.feasible,
        blocks=blocks,
        frames=[SpanOut(start=w.start, end=w.end) for w in frame_spans(week)],
        unscheduled=[ItemRef(id=i.id, title=i.title) for i in items if not i.windows],
    )


def frame_spans(week: Week) -> list[Window]:
    """The week's work-frame time as merged UTC windows, clipped to the week.

    Starts a day early so an overnight frame from the Sunday before still
    shows its tail on Monday morning.
    """
    start, end = week.horizon()
    windows = [
        w
        for frame in week.work_frames
        for w in work_frame_windows(frame, week.start - timedelta(days=1), week.start + timedelta(days=6))
    ]
    clipped = [Window(max(w.start, start), min(w.end, end)) for w in windows if w.end > start and w.start < end]
    return merge_windows(clipped)


def main() -> None:
    """Run the API on this machine only, reloading on code changes."""
    import uvicorn

    uvicorn.run("mycal.api:app", host="127.0.0.1", port=8000, reload=True)
