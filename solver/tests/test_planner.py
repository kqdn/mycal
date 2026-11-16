"""Planning spans of weeks from the database, below the API."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from mycal import FlexPreset, Item, SolverSettings, WorkFrame, store
from mycal.planner import MAX_SPAN_WEEKS, effective_item, plan_weeks

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


@pytest.mark.parametrize(
    "item, start, end",
    [
        (
            Item("Phone call", FlexPreset.DAY_RANGE, estimate_min=30,
                 preset_params={"day": date(2026, 11, 17), "start_time": time(17), "end_time": time(20)}),
            time(17),
            time(20),
        ),
        (
            Item("Piano", FlexPreset.DAYS, estimate_min=150, max_chunk_min=30, one_block_per_day=True,
                 preset_params={"week": W1, "weekdays": [0, 1, 2, 3, 4], "start_time": time(18), "end_time": time(20)}),
            time(18),
            time(20),
        ),
    ],
    ids=["day_range", "days"],
)
def test_a_time_range_overrides_the_work_frames(item: Item, start: time, end: time) -> None:
    # Work frames end at 6pm, but the item's own range is used instead of them (PRD decision log, Nov 15).
    conn = store.connect(":memory:")
    store.save_settings(conn, SolverSettings(LA))
    store.put_work_frame(conn, WorkFrame("Weekdays", [0, 1, 2, 3, 4], time(9), time(18), LA))
    store.put_item(conn, item)

    assert plan_weeks(conn, store.load_settings(conn), W1, W1, NOW) == {W1: True}

    zone = ZoneInfo(LA)
    blocks = [b for b in store.list_blocks(conn) if b.item_id == item.id]
    assert blocks
    for b in blocks:
        local_start, local_end = b.start.astimezone(zone), b.end.astimezone(zone)
        assert local_start.date() == local_end.date()
        assert start <= local_start.time() and local_end.time() <= end
    assert any(b.start.astimezone(zone).time() >= time(18) for b in blocks)  # outside the 9 to 6 frames


def test_a_fixed_event_across_a_span_edge_is_saved_whole() -> None:
    # Sun Nov 22, 11pm to Mon Nov 23, 1am: the span for week 1 ends at Sunday midnight.
    conn = store.connect(":memory:")
    store.save_settings(conn, SolverSettings(LA))
    start, end = pacific(11, 22, 23), pacific(11, 23, 1)
    late = Item("Late shift", FlexPreset.EXACT, preset_params={"start": start, "end": end})
    store.put_item(conn, late)

    plan_weeks(conn, store.load_settings(conn), W1, W1, NOW)
    [first] = [b for b in store.list_blocks(conn) if b.item_id == late.id]
    plan_weeks(conn, store.load_settings(conn), W2, W2, NOW)
    [again] = [b for b in store.list_blocks(conn) if b.item_id == late.id]

    assert (first.start, first.end) == (start, end)
    assert (again.id, again.start, again.end) == (first.id, start, end)


@pytest.mark.parametrize(
    "slot, estimate, longest, planned",
    [
        (15, 20, 20, (30, 15)),  # estimate up, longest session down
        (15, 20, 10, (30, 15)),  # a longest session is never below one slot
        (15, 60, 30, (60, 30)),  # on the grid: unchanged
        (10, 25, 25, (30, 20)),  # the slot size is a setting
    ],
)
def test_effective_item_rounds_lengths_to_the_slot_grid(slot: int, estimate: int, longest: int, planned: tuple[int, int]) -> None:
    item = Item("Read", FlexPreset.DAY, preset_params={"day": date(2026, 11, 17)}, estimate_min=estimate, max_chunk_min=longest)
    settings = SolverSettings(LA, slot_min=slot)

    rounded = effective_item(item, [], [], settings, NOW)

    assert (rounded.estimate_min, rounded.max_chunk_min) == planned
    assert (item.estimate_min, item.max_chunk_min) == (estimate, longest)  # the stored item never changes


def test_a_stored_estimate_off_the_grid_keeps_its_value_after_planning() -> None:
    conn = store.connect(":memory:")
    store.save_settings(conn, SolverSettings(LA))
    store.put_work_frame(conn, WorkFrame("Weekdays", [0, 1, 2, 3, 4], time(9), time(18), LA))
    item = Item("Read", FlexPreset.DAY, preset_params={"day": date(2026, 11, 17)}, estimate_min=20)
    store.put_item(conn, item)

    plan_weeks(conn, store.load_settings(conn), W1, W1, NOW)

    [block] = store.list_blocks(conn)
    assert (block.end - block.start).seconds // 60 == 30
    assert store.list_items(conn)[0].estimate_min == 20
