"""Compile repeating WorkFrames into exact UTC windows. Not part of the solver."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mycal.model import Window, WorkFrame


def work_frame_windows(frame: WorkFrame, start_date: date, end_date: date) -> list[Window]:
    """Return the frame's UTC windows for every start day in [start_date, end_date].

    Both dates are inclusive local dates. A day counts if its weekday is in
    `frame.weekdays`; that is the day the frame starts. A frame that crosses
    midnight ends the next day, even when that day is past `end_date`.

    The UTC offset is looked up separately for the start and the end, so a
    frame keeps its local hours across DST, and a frame spanning the clock
    change is an hour shorter or longer in real time. Following zoneinfo, a
    local time that does not exist (spring forward) is read with the old
    offset, and an ambiguous one (fall back) uses its first occurrence.
    """
    if end_date < start_date:
        raise ValueError("end_date must not be before start_date")

    zone = ZoneInfo(frame.timezone)
    crosses_midnight = frame.end_time < frame.start_time
    windows: list[Window] = []

    day = start_date
    while day <= end_date:
        if day.weekday() in frame.weekdays:
            end_day = day + timedelta(days=1) if crosses_midnight else day
            start = datetime.combine(day, frame.start_time, tzinfo=zone)
            end = datetime.combine(end_day, frame.end_time, tzinfo=zone)
            windows.append(Window(start.astimezone(UTC), end.astimezone(UTC)))
        day += timedelta(days=1)

    return windows


def merge_windows(windows: list[Window]) -> list[Window]:
    """Sort windows and merge any that overlap or touch."""
    merged: list[Window] = []
    for w in sorted(windows, key=lambda w: w.start):
        if merged and w.start <= merged[-1].end:
            last = merged.pop()
            w = Window(last.start, max(last.end, w.end))
        merged.append(w)
    return merged


def day_capacity_min(frames: list[WorkFrame], day: date, timezone: str) -> int:
    """Minutes of work-frame time inside one local day (midnight to midnight in `timezone`).

    Overlapping frames count once, and the tail of an overnight frame from the
    day before counts toward this day.
    """
    zone = ZoneInfo(timezone)
    day_start = datetime.combine(day, time(), tzinfo=zone).astimezone(UTC)
    day_end = datetime.combine(day + timedelta(days=1), time(), tzinfo=zone).astimezone(UTC)
    inside = [
        Window(max(w.start, day_start), min(w.end, day_end))
        for frame in frames
        for w in work_frame_windows(frame, day - timedelta(days=1), day)
        if w.start < day_end and w.end > day_start
    ]
    return sum((w.end - w.start) // timedelta(minutes=1) for w in merge_windows(inside))
