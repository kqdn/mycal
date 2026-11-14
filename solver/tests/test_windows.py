from datetime import UTC, date, datetime, time, timedelta

import pytest

from mycal import Window, WorkFrame, work_frame_windows

LA = "America/Los_Angeles"
EVERY_DAY = list(range(7))
FRIDAY, SATURDAY = 4, 5


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_daily_frame_keeps_local_hours_across_spring_forward() -> None:
    frame = WorkFrame("Daytime", EVERY_DAY, time(9), time(18), LA)

    windows = work_frame_windows(frame, date(2027, 3, 13), date(2027, 3, 15))

    assert windows == [
        Window(utc(2027, 3, 13, 17), utc(2027, 3, 14, 2)),  # PST, UTC-8
        Window(utc(2027, 3, 14, 16), utc(2027, 3, 15, 1)),  # PDT, UTC-7
        Window(utc(2027, 3, 15, 16), utc(2027, 3, 16, 1)),
    ]
    assert all(w.end - w.start == timedelta(hours=9) for w in windows)


def test_overnight_frame_belongs_to_its_start_day() -> None:
    frame = WorkFrame("Late nights", [FRIDAY, SATURDAY], time(21), time(1), LA)

    # Mon Nov 16 to Fri Nov 20, 2026: Saturday's frame is outside the range.
    windows = work_frame_windows(frame, date(2026, 11, 16), date(2026, 11, 20))

    assert windows == [Window(utc(2026, 11, 21, 5), utc(2026, 11, 21, 9))]


def test_overnight_frame_through_clock_change_is_one_hour_shorter() -> None:
    frame = WorkFrame("All-nighter", [SATURDAY], time(22), time(4), LA)

    windows = work_frame_windows(frame, date(2027, 3, 13), date(2027, 3, 13))

    # 10pm PST to 4am PDT: the clock shows 6 hours, 5 actually pass.
    assert windows == [Window(utc(2027, 3, 14, 6), utc(2027, 3, 14, 11))]
    assert windows[0].end - windows[0].start == timedelta(hours=5)


def test_reversed_date_range_rejected() -> None:
    frame = WorkFrame("Daytime", EVERY_DAY, time(9), time(18), LA)
    with pytest.raises(ValueError):
        work_frame_windows(frame, date(2027, 3, 15), date(2027, 3, 13))
