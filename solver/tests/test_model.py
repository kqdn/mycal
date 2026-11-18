from datetime import UTC, datetime, time, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from mycal import Block, BlockStatus, FlexPreset, Item, OnMiss, Window, WorkFrame

MON_9AM = datetime(2026, 11, 16, 17, 0, tzinfo=UTC)


def test_entities_get_unique_uuids() -> None:
    a = Item(title="Gym", flex_preset=FlexPreset.DAYS)
    b = Item(title="Gym", flex_preset=FlexPreset.DAYS)
    assert isinstance(a.id, UUID)
    assert a.id != b.id


def test_one_block_per_day_is_off_by_default() -> None:
    assert Item(title="Problem set", flex_preset=FlexPreset.BEFORE_DEADLINE).one_block_per_day is False


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        Window(start=datetime(2026, 11, 16, 9), end=datetime(2026, 11, 16, 10))


def test_non_utc_datetime_rejected() -> None:
    pacific = timezone(timedelta(hours=-8))
    with pytest.raises(ValueError):
        Item(
            title="Write code",
            flex_preset=FlexPreset.BEFORE_DEADLINE,
            deadline=datetime(2026, 11, 20, 17, tzinfo=pacific),
        )


@pytest.mark.parametrize("length", [timedelta(0), timedelta(minutes=-15)])
def test_window_rejects_empty_or_reversed(length: timedelta) -> None:
    with pytest.raises(ValueError):
        Window(start=MON_9AM, end=MON_9AM + length)


def test_block_rejects_non_utc_completed_at() -> None:
    item = Item(title="Lab", flex_preset=FlexPreset.DAY)
    with pytest.raises(ValueError):
        Block(
            item_id=item.id,
            start=MON_9AM,
            end=MON_9AM + timedelta(hours=1),
            completed_at=datetime(2026, 11, 16, 10),
        )


def test_work_frame_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError):
        WorkFrame("Weekdays", [0, 1, 2, 3, 4], time(9), time(18), "Not/AZone")


def test_work_frame_can_cross_midnight() -> None:
    frame = WorkFrame("Late nights", [4, 5], time(21), time(1), "America/Los_Angeles")
    assert frame.end_time < frame.start_time


def test_work_frame_rejects_zero_length() -> None:
    with pytest.raises(ValueError):
        WorkFrame("Empty", [0], time(9), time(9), "America/Los_Angeles")



def test_block_missed_action_is_never_ask() -> None:
    start = datetime(2026, 11, 16, 17, tzinfo=UTC)
    with pytest.raises(ValueError):
        Block(uuid4(), start, start + timedelta(hours=1), status=BlockStatus.MISSED, missed_action=OnMiss.ASK)


@pytest.mark.parametrize("status", [BlockStatus.PLANNED, BlockStatus.DONE])
def test_block_without_a_missed_part_has_no_missed_action(status: BlockStatus) -> None:
    start = datetime(2026, 11, 16, 17, tzinfo=UTC)
    with pytest.raises(ValueError):
        Block(uuid4(), start, start + timedelta(hours=1), status=status, missed_action=OnMiss.SKIP)
