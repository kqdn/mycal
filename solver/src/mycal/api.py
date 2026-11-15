"""Milestone 2 API: load a week file, solve it and return the schedule as JSON.

Not part of the solver: like demo.py, this module is a caller. It reads files
and serves HTTP, then calls solve() through plan_week(). The core modules
never import it.

All times in responses are UTC. The page converts them to the week's
timezone only for display.

Solved weeks are cached on disk (a stopgap until Milestone 3 storage), keyed
on the week, the week file's bytes and SOLVER_VERSION. An unchanged file
always gets the same plan back, and any edit to the file or the code solves
again.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
import tomllib
from datetime import date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mycal.demo import Week, parse_week, plan_week
from mycal.model import FlexPreset, Item, Window
from mycal.solve import SolveResult
from mycal.windows import merge_windows, work_frame_windows

WEEKS_DIR_ENV = "MYCAL_WEEKS_DIR"
CACHE_DIR_ENV = "MYCAL_CACHE_DIR"

# A child of uvicorn's logger, so lines show in the server console at INFO
# (uvicorn configures its loggers in the worker process, even with reload).
log = logging.getLogger("uvicorn.error.mycal")


def _solver_version() -> str:
    """A hash of every .py file in the package plus the OR-Tools version.

    Everything that shapes a cached response is in here: the solver, the week
    file parser and the response models. So any code change, or an OR-Tools
    upgrade, makes old cache files miss without anyone bumping a number.
    """
    digest = hashlib.sha256(f"ortools {version('ortools')}".encode())
    package = Path(__file__).parent
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


SOLVER_VERSION = _solver_version()

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


def cache_dir() -> Path:
    return Path(os.environ.get(CACHE_DIR_ENV, "cache"))


@app.get("/api/weeks/{week_start}")
def get_week(week_start: date) -> WeekOut:
    """Solve weeks/<week_start>.toml, or return the cached plan for these exact bytes.

    A week that cannot be solved still returns 200 (and is cached, since the
    same file gives the same answer). Errors are not cached.
    """
    path = weeks_dir() / f"{week_start.isoformat()}.toml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No week file for {week_start}")
    data = path.read_bytes()
    cached = cache_path(week_start, data)
    if (hit := _read_cache(cached)) is not None:
        log.info("%s hit", week_start)
        return hit

    try:
        week = parse_week(tomllib.loads(data.decode("utf-8")))
        began = time.perf_counter()
        items, result = plan_week(week)
    except (KeyError, ValueError, tomllib.TOMLDecodeError) as error:
        raise HTTPException(status_code=400, detail=f"Bad week file: {error}") from error
    log.info("%s miss, solved in %.2fs, %s", week_start, time.perf_counter() - began, result.status)

    out = _week_out(week, items, result)
    _write_cache(cached, out)
    return out


def cache_path(week_start: date, data: bytes) -> Path:
    """Where the plan for this week file's exact bytes, under this SOLVER_VERSION, is cached."""
    digest = hashlib.sha256(f"{week_start.isoformat()} {SOLVER_VERSION} ".encode())
    digest.update(data)
    key = digest.hexdigest()[:16]
    return cache_dir() / f"{week_start.isoformat()}-{key}.json"


def _read_cache(path: Path) -> WeekOut | None:
    """The cached plan, or None. A file that can't be read or doesn't validate is a miss."""
    if not path.is_file():
        return None
    try:
        return WeekOut.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:  # pydantic's ValidationError is a ValueError
        log.warning("Ignoring unreadable cache file %s: %s", path.name, error)
        return None


def _write_cache(path: Path, out: WeekOut) -> None:
    """Write atomically (temp file, then rename), then drop older plans for the same week.

    A failed write only costs a re-solve next time, so it is logged, not raised.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, suffix=".tmp", delete=False) as tmp:
            tmp.write(out.model_dump_json().encode())
        os.replace(tmp.name, path)
        week_start = path.name[:10]
        for old in path.parent.glob(f"{week_start}-*.json"):
            if old != path:
                old.unlink(missing_ok=True)
    except OSError as error:
        log.warning("Could not write cache file %s: %s", path.name, error)


def _week_out(week: Week, items: list[Item], result: SolveResult) -> WeekOut:
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
