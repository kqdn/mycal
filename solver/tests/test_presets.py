"""Preset compilation on the week of Mon Nov 16, 2026 in Los Angeles (PST, UTC-8)."""

from datetime import UTC, date, datetime, time
from typing import Any

import pytest

from mycal import FlexPreset, Item, Window, WorkFrame, compile_windows

LA = "America/Los_Angeles"
MON, WED, FRI, SUN = 0, 2, 4, 6
WEEKDAYS = WorkFrame("Weekdays", [0, 1, 2, 3, 4], time(9), time(18), LA)

# Mon Nov 16 00:00 PST to Mon Nov 23 00:00 PST
WEEK_START = datetime(2026, 11, 16, 8, tzinfo=UTC)
WEEK_END = datetime(2026, 11, 23, 8, tzinfo=UTC)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def compile_item(
    preset: FlexPreset,
    params: dict[str, Any],
    frames: list[WorkFrame] = [WEEKDAYS],
    deadline: datetime | None = None,
    horizon_start: datetime = WEEK_START,
) -> list[Window]:
    item = Item("Test", preset, preset_params=params, deadline=deadline)
    return compile_windows(item, frames, LA, horizon_start, WEEK_END)


def test_exact_is_one_window() -> None:
    lecture = Window(utc(2026, 11, 17, 19), utc(2026, 11, 17, 20, 30))
    assert compile_item(FlexPreset.EXACT, {"start": lecture.start, "end": lecture.end}) == [lecture]


def test_exact_in_progress_is_not_cut() -> None:
    lecture = Window(utc(2026, 11, 17, 19), utc(2026, 11, 17, 20, 30))
    windows = compile_item(
        FlexPreset.EXACT,
        {"start": lecture.start, "end": lecture.end},
        horizon_start=utc(2026, 11, 17, 19, 30),
    )
    assert windows == [lecture]


def test_day_uses_that_days_work_frame() -> None:
    windows = compile_item(FlexPreset.DAY, {"day": date(2026, 11, 18)})
    assert windows == [Window(utc(2026, 11, 18, 17), utc(2026, 11, 19, 2))]


def test_day_without_a_frame_is_empty() -> None:
    assert compile_item(FlexPreset.DAY, {"day": date(2026, 11, 21)}) == []


def test_day_range() -> None:
    params = {"day": date(2026, 11, 19), "start_time": time(17), "end_time": time(21)}
    windows = compile_item(FlexPreset.DAY_RANGE, params)
    assert windows == [Window(utc(2026, 11, 20, 1), utc(2026, 11, 20, 5))]


def test_days_uses_work_frames_on_chosen_weekdays() -> None:
    windows = compile_item(FlexPreset.DAYS, {"weekdays": [MON, WED, FRI]})
    assert windows == [
        Window(utc(2026, 11, 16, 17), utc(2026, 11, 17, 2)),
        Window(utc(2026, 11, 18, 17), utc(2026, 11, 19, 2)),
        Window(utc(2026, 11, 20, 17), utc(2026, 11, 21, 2)),
    ]


def test_days_with_time_range() -> None:
    params = {"weekdays": [MON, WED], "start_time": time(6), "end_time": time(8)}
    windows = compile_item(FlexPreset.DAYS, params)
    assert windows == [
        Window(utc(2026, 11, 16, 14), utc(2026, 11, 16, 16)),
        Window(utc(2026, 11, 18, 14), utc(2026, 11, 18, 16)),
    ]


def test_before_deadline_clips_to_now_and_deadline() -> None:
    windows = compile_item(
        FlexPreset.BEFORE_DEADLINE,
        {},
        deadline=utc(2026, 11, 19, 21),  # Thu 1pm PST
        horizon_start=utc(2026, 11, 17, 20),  # Tue noon PST
    )
    assert windows == [
        Window(utc(2026, 11, 17, 20), utc(2026, 11, 18, 2)),
        Window(utc(2026, 11, 18, 17), utc(2026, 11, 19, 2)),
        Window(utc(2026, 11, 19, 17), utc(2026, 11, 19, 21)),
    ]


def test_overnight_frame_from_before_horizon_contributes_its_tail() -> None:
    sunday_night = WorkFrame("Sunday night", [SUN], time(21), time(1), LA)
    windows = compile_item(
        FlexPreset.BEFORE_DEADLINE,
        {},
        frames=[sunday_night],
        deadline=utc(2026, 11, 22, 12),
    )
    # Sun Nov 15 9pm to Mon 1am, clipped to the horizon starting Mon midnight.
    assert windows == [Window(utc(2026, 11, 16, 8), utc(2026, 11, 16, 9))]


def test_overlapping_frames_merge() -> None:
    morning = WorkFrame("Morning", [WED], time(9), time(13), LA)
    afternoon = WorkFrame("Afternoon", [WED], time(12), time(18), LA)
    windows = compile_item(FlexPreset.DAY, {"day": date(2026, 11, 18)}, frames=[morning, afternoon])
    assert windows == [Window(utc(2026, 11, 18, 17), utc(2026, 11, 19, 2))]


def test_custom_windows_are_clipped_to_horizon() -> None:
    painted = [Window(utc(2026, 11, 22, 20), utc(2026, 11, 23, 12))]
    windows = compile_item(FlexPreset.CUSTOM, {"windows": painted})
    assert windows == [Window(utc(2026, 11, 22, 20), WEEK_END)]


def test_missing_param_rejected() -> None:
    with pytest.raises(ValueError, match="day"):
        compile_item(FlexPreset.DAY, {})


def test_before_deadline_without_deadline_rejected() -> None:
    with pytest.raises(ValueError):
        compile_item(FlexPreset.BEFORE_DEADLINE, {})
