"""Problem setup: settings, chunk splitting, remaining work and slot rounding."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from mycal import Block, BlockStatus, Constraint, FlexPreset, Item, SolverSettings, Window
from mycal.problem import Target, build_problem, slot_start, split_slots

LA = "America/Los_Angeles"
SETTINGS = SolverSettings(timezone=LA)
MON_9AM = datetime(2026, 11, 16, 17, tzinfo=UTC)  # 9am PST
DAY = Window(MON_9AM, MON_9AM + timedelta(hours=8))


def task(minutes: int | None, max_chunk_min: int | None = None, windows: list[Window] = [DAY]) -> Item:
    return Item("Task", FlexPreset.CUSTOM, windows=windows, estimate_min=minutes, max_chunk_min=max_chunk_min)


def test_settings_need_a_timezone() -> None:
    with pytest.raises(TypeError):
        SolverSettings()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        SolverSettings(timezone="Not/AZone")


@pytest.mark.parametrize(
    ("total", "max_chunk_min", "sizes"),
    [
        (20, None, [20]),
        (16, 120, [8, 8]),  # 4h, 2h max: 2h + 2h
        (20, 120, [7, 7, 6]),  # 5h, 2h max: 105 + 105 + 90 min
        (3, 120, [3]),
    ],
)
def test_split_slots_is_even(total: int, max_chunk_min: int | None, sizes: list[int]) -> None:
    assert split_slots(total, max_chunk_min, 15) == sizes


def test_done_and_locked_blocks_reduce_remaining_work() -> None:
    item = task(240, max_chunk_min=120)
    sunday = MON_9AM - timedelta(days=1)
    done = Block(item.id, sunday, sunday + timedelta(hours=2), status=BlockStatus.DONE, actual_min=90)
    locked = Block(item.id, MON_9AM, MON_9AM + timedelta(hours=1), locked=True)
    problem = build_problem([item], [done, locked], [], SETTINGS)

    assert [c.size for c in problem.chunks] == [6]  # 240 - 90 - 60 = 90 min
    assert problem.kept == [done, locked]


def test_unlocked_planned_block_passes_on_its_id() -> None:
    item = task(60)
    old = Block(item.id, MON_9AM, MON_9AM + timedelta(hours=1))
    problem = build_problem([item], [old], [], SETTINGS)

    assert problem.kept == []
    assert problem.chunks[0].block_id == old.id


def test_window_edges_round_inward_to_slots() -> None:
    window = Window(MON_9AM + timedelta(minutes=15), MON_9AM + timedelta(minutes=105))
    problem = build_problem([task(60, windows=[window])], [], [], SolverSettings(LA, slot_min=30))

    starts = [slot_start(s, 30) for s in problem.chunks[0].candidates]
    assert starts == [MON_9AM + timedelta(minutes=30)]


def test_item_without_estimate_needs_a_single_window() -> None:
    two_windows = [DAY, Window(DAY.start + timedelta(days=1), DAY.end + timedelta(days=1))]
    with pytest.raises(ValueError, match="estimate"):
        build_problem([task(None, windows=two_windows)], [], [], SETTINGS)


def test_unsupported_hard_constraint_rejected() -> None:
    with pytest.raises(ValueError, match="buffer"):
        build_problem([], [], [Constraint(kind="buffer", hard=True)], SETTINGS)


def test_daily_limit_defaults_to_every_day() -> None:
    limit = Constraint(kind="daily_limit", params={"max_min": 180}, hard=True)
    [parsed] = build_problem([], [], [limit], SETTINGS).daily_limits
    assert (parsed.max_min, parsed.weekdays) == (180, (0, 1, 2, 3, 4, 5, 6))


@pytest.mark.parametrize(
    ("params", "hard"),
    [
        ({"max_min": 180}, False),  # soft is not supported yet
        ({}, True),
        ({"max_min": -1}, True),
        ({"max_min": 180, "weekdays": [7]}, True),
        ({"max_min": 180, "days": [5]}, True),
    ],
)
def test_bad_daily_limit_rejected(params: dict[str, Any], hard: bool) -> None:
    with pytest.raises(ValueError, match="daily_limit"):
        build_problem([], [], [Constraint(kind="daily_limit", params=params, hard=hard)], SETTINGS)


def time_preference(**params: Any) -> Constraint:
    return Constraint(kind="time_preference", params={"windows": [DAY], **params})


def test_time_preference_weight_is_scaled_to_an_integer() -> None:
    pref = time_preference(mode="avoid")
    pref.weight = 1.5
    [parsed] = build_problem([], [], [pref], SETTINGS).preferences
    assert (parsed.avoid, parsed.weight, parsed.target) == (True, 150, Target())


@pytest.mark.parametrize(
    "constraint",
    [
        Constraint(kind="time_preference", params={"windows": [DAY]}, hard=True),
        Constraint(kind="time_preference", params={"weekdays": [0], "start_time": "x", "end_time": "y"}),
        time_preference(mode="sometimes"),
        time_preference(item_ids=[uuid4()]),  # no such item
        time_preference(days=[0]),
        Constraint(kind="time_preference", params={"windows": [DAY]}, weight=-1),
    ],
)
def test_bad_time_preference_rejected(constraint: Constraint) -> None:
    with pytest.raises(ValueError, match="time_preference"):
        build_problem([], [], [constraint], SETTINGS)


def test_target_matches_items_and_series_occurrences() -> None:
    plain = task(60)
    series_id = uuid4()
    occurrence = Item("Gym", FlexPreset.CUSTOM, series_id=series_id, occurrence_date=MON_9AM.date())
    assert Target().matches(plain)
    assert Target(item_ids=frozenset({plain.id})).matches(plain)
    assert not Target(item_ids=frozenset({plain.id})).matches(occurrence)
    assert Target(series_ids=frozenset({series_id})).matches(occurrence)
    assert not Target(series_ids=frozenset({series_id})).matches(plain)


def test_rest_between_defaults_to_one_free_day() -> None:
    [parsed] = build_problem([], [], [Constraint(kind="rest_between")], SETTINGS).rests
    assert (parsed.min_gap_days, parsed.weight) == (1, 100)


@pytest.mark.parametrize(
    "constraint",
    [
        Constraint(kind="rest_between", hard=True),
        Constraint(kind="rest_between", params={"min_gap_days": 0}),
        Constraint(kind="rest_between", params={"min_gap_days": 1.5}),
        Constraint(kind="rest_between", params={"gap": 1}),
        Constraint(kind="rest_between", params={"series_ids": ["gym"]}),
    ],
)
def test_bad_rest_between_rejected(constraint: Constraint) -> None:
    with pytest.raises(ValueError, match="rest_between"):
        build_problem([], [], [constraint], SETTINGS)
