""""N times a week" items with fewer days left than sessions get one session per day left (Milestone 7)."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from mycal import Block, BlockStatus, FlexPreset, Item, OnMiss, SolverSettings, WorkFrame, store
from mycal.planner import effective_item, plan_weeks, shortfalls

LA = "America/Los_Angeles"
ZONE = ZoneInfo(LA)
W1 = date(2026, 11, 16)  # Monday
MON, WED, FRI = 0, 2, 4
DAYTIME = WorkFrame("Weekdays", [0, 1, 2, 3, 4], time(9), time(18), LA)
SETTINGS = SolverSettings(LA)


def local(day: int, hour: int) -> datetime:
    """A local moment in November 2026, as UTC."""
    return datetime(2026, 11, day, hour, tzinfo=ZONE).astimezone(UTC)


def workout() -> Item:
    """3 sessions of 1h, on Mon, Wed or Fri, never two on one day."""
    return Item(
        "Workout",
        FlexPreset.DAYS,
        preset_params={"week": W1, "weekdays": [MON, WED, FRI]},
        estimate_min=180,
        max_chunk_min=60,
        one_block_per_day=True,
    )


def test_enough_days_left_means_no_shortfall() -> None:
    item = workout()
    sunday = local(15, 12)

    assert shortfalls([item], [], [DAYTIME], SETTINGS, sunday) == []
    assert effective_item(item, [], [DAYTIME], SETTINGS, sunday).estimate_min == 180


def test_created_on_tuesday_it_gets_a_session_on_each_day_left() -> None:
    item = workout()
    tuesday = local(17, 12)

    [short] = shortfalls([item], [], [DAYTIME], SETTINGS, tuesday)

    assert (short.title, short.sessions, short.gets) == ("Workout", 3, 2)
    assert short.days_left == (date(2026, 11, 18), date(2026, 11, 20))
    assert effective_item(item, [], [DAYTIME], SETTINGS, tuesday).estimate_min == 120


def test_the_week_is_planned_instead_of_failing() -> None:
    item = workout()
    conn = store.connect(":memory:")
    store.save_settings(conn, SETTINGS)
    store.put_work_frame(conn, DAYTIME)
    store.put_item(conn, item)

    plan_weeks(conn, store.load_settings(conn), W1, W1, local(17, 12))

    days = sorted(b.start.astimezone(ZONE).date() for b in store.list_blocks(conn))
    assert days == [date(2026, 11, 18), date(2026, 11, 20)]


def test_a_rescheduled_miss_with_no_day_left_for_it_is_a_shortfall() -> None:
    item = workout()
    missed = Block(item.id, local(16, 9), local(16, 10), status=BlockStatus.MISSED, missed_action=OnMiss.RESCHEDULE)
    done = Block(item.id, local(18, 9), local(18, 10), status=BlockStatus.DONE)
    thursday = local(19, 12)

    [short] = shortfalls([item], [missed, done], [DAYTIME], SETTINGS, thursday)

    assert (short.sessions, short.gets, short.days_left) == (3, 2, (date(2026, 11, 20),))


def test_a_skipped_miss_is_settled_so_no_shortfall() -> None:
    item = workout()
    skipped = Block(item.id, local(16, 9), local(16, 10), status=BlockStatus.MISSED, missed_action=OnMiss.SKIP)
    done = Block(item.id, local(18, 9), local(18, 10), status=BlockStatus.DONE)

    assert shortfalls([item], [skipped, done], [DAYTIME], SETTINGS, local(19, 12)) == []
