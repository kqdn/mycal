"""Compile an item's flexibility preset into UTC windows. Not part of the solver.

Expected `preset_params` per preset (local dates and times are in the
`timezone` passed to compile_windows):

    EXACT            start, end: UTC datetimes
    DAY              day: local date
    DAY_RANGE        day: local date; start_time, end_time: local times
    DAYS             weekdays: list of ints (0 = Monday);
                     optional start_time and end_time (both or neither)
    BEFORE_DEADLINE  none; uses item.deadline
    CUSTOM           windows: list of Window
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from mycal.model import FlexPreset, Item, Window, WorkFrame
from mycal.windows import work_frame_windows


def compile_windows(
    item: Item,
    work_frames: list[WorkFrame],
    timezone: str,
    horizon_start: datetime,
    horizon_end: datetime,
) -> list[Window]:
    """Return the item's allowed windows inside [horizon_start, horizon_end].

    Windows are clipped to the horizon (and to the deadline for
    BEFORE_DEADLINE), then sorted and merged where they overlap or touch, so a
    block can span two adjacent work frames. EXACT windows are never cut: a
    pinned item keeps its full length and is dropped only if it lies entirely
    outside the horizon. The item is not modified.
    """
    Window(horizon_start, horizon_end)  # validates UTC and order
    params = item.preset_params
    preset = item.flex_preset

    if preset is FlexPreset.EXACT:
        window = Window(_param(params, "start", datetime), _param(params, "end", datetime))
        overlaps = window.start < horizon_end and window.end > horizon_start
        return [window] if overlaps else []

    if preset is FlexPreset.DAY:
        day = _param(params, "day", date)
        windows = [w for frame in work_frames for w in work_frame_windows(frame, day, day)]
    elif preset is FlexPreset.DAY_RANGE:
        day = _param(params, "day", date)
        frame = _range_frame(params, [day.weekday()], timezone)
        windows = work_frame_windows(frame, day, day)
    elif preset is FlexPreset.DAYS:
        weekdays = _param(params, "weekdays", list)
        if "start_time" in params or "end_time" in params:
            frames = [_range_frame(params, weekdays, timezone)]
        else:
            frames = [
                replace(f, weekdays=[d for d in f.weekdays if d in weekdays]) for f in work_frames
            ]
        windows = _horizon_windows(frames, timezone, horizon_start, horizon_end)
    elif preset is FlexPreset.BEFORE_DEADLINE:
        if item.deadline is None:
            raise ValueError("BEFORE_DEADLINE needs item.deadline")
        horizon_end = min(horizon_end, item.deadline)
        if horizon_end <= horizon_start:
            return []
        windows = _horizon_windows(work_frames, timezone, horizon_start, horizon_end)
    elif preset is FlexPreset.CUSTOM:
        windows = _param(params, "windows", list)
    else:
        raise ValueError(f"Unknown preset {preset!r}")

    return _merge(_clip(windows, horizon_start, horizon_end))


def _param(params: dict[str, Any], key: str, kind: type) -> Any:
    """Fetch params[key], raising ValueError if it is missing or the wrong type."""
    if key not in params:
        raise ValueError(f"preset_params is missing {key!r}")
    value = params[key]
    # datetime is a subclass of date, so reject it explicitly where a date is expected.
    if not isinstance(value, kind) or (kind is date and isinstance(value, datetime)):
        raise ValueError(f"preset_params[{key!r}] must be {kind.__name__}, got {value!r}")
    return value


def _range_frame(params: dict[str, Any], weekdays: list[int], timezone: str) -> WorkFrame:
    """A temporary WorkFrame for a local time range, so DST and midnight logic stays in one place."""
    start = _param(params, "start_time", time)
    end = _param(params, "end_time", time)
    return WorkFrame("time range", weekdays, start, end, timezone)


def _horizon_windows(
    frames: list[WorkFrame], timezone: str, horizon_start: datetime, horizon_end: datetime
) -> list[Window]:
    """All frame windows for the local dates the horizon touches.

    Starts one day early so an overnight frame that began the day before the
    horizon still contributes its tail.
    """
    zone = ZoneInfo(timezone)
    first = horizon_start.astimezone(zone).date() - timedelta(days=1)
    last = horizon_end.astimezone(zone).date()
    return [w for frame in frames for w in work_frame_windows(frame, first, last)]


def _clip(windows: list[Window], start: datetime, end: datetime) -> list[Window]:
    """Cut windows to [start, end], dropping any that end up empty."""
    clipped = []
    for w in windows:
        lo, hi = max(w.start, start), min(w.end, end)
        if lo < hi:
            clipped.append(Window(lo, hi))
    return clipped


def _merge(windows: list[Window]) -> list[Window]:
    """Sort windows and merge any that overlap or touch."""
    merged: list[Window] = []
    for w in sorted(windows, key=lambda w: w.start):
        if merged and w.start <= merged[-1].end:
            last = merged.pop()
            w = Window(last.start, max(last.end, w.end))
        merged.append(w)
    return merged
