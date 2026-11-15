"""Planning spans of weeks from the database, below the API."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from mycal import FlexPreset, Item, SolverSettings, WorkFrame, store
from mycal.planner import MAX_SPAN_WEEKS, plan_weeks

LA = "America/Los_Angeles"
W1, W2, W3, W4 = date(2026, 11, 16), date(2026, 11, 23), date(2026, 11, 30), date(2026, 12, 7)
NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


def pacific(month: int, day: int, hour: int) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=ZoneInfo(LA)).astimezone(UTC)


def test_planning_resumes_as_a_joint_span_after_a_broken_week() -> None:
    assert MAX_SPAN_WEEKS == 2
    conn = store.connect(":memory:")
    store.save_settings(conn, SolverSettings(LA))
    store.put_work_frame(conn, WorkFrame("Mornings", [0, 1, 2, 3, 4], time(9), time(10), LA))  # 5h a week
    for title in ("Dentist", "Exam"):  # the same hour on Tue Nov 24: week 2 can't be planned
        store.put_item(conn, Item(title, FlexPreset.EXACT, preset_params={"start": pacific(11, 24, 9), "end": pacific(11, 24, 10)}))
    # 8h due Fri Dec 11: only weeks 3 and 4 together hold it.
    task = Item("Course", FlexPreset.BEFORE_DEADLINE, estimate_min=8 * 60, max_chunk_min=60, deadline=pacific(12, 11, 17))
    store.put_item(conn, task)

    outcome = plan_weeks(conn, store.load_settings(conn), W2, W4, NOW)

    assert outcome == {W2: False, W3: True, W4: True}
    course = [b for b in store.list_blocks(conn) if b.item_id == task.id]
    assert sum((b.end - b.start).seconds // 60 for b in course) == 8 * 60
