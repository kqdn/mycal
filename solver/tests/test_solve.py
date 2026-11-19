"""Solver tests on small hand-built weeks (Mon Nov 16, 2026, Los Angeles, PST).

Most tests only check that the hard constraints hold, via assert_valid. Exact
positions are asserted only where a case has one valid answer.
"""

import copy
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mycal import Block, BlockStatus, Constraint, FlexPreset, Item, OnMiss, SolveResult, SolverSettings, Window, solve
from mycal.problem import covered_min, is_kept, session_min

LA = "America/Los_Angeles"
SETTINGS = SolverSettings(timezone=LA)
ENGINES = ["backtracking", "cp_sat"]
_engine = ENGINES[0]


@pytest.fixture(autouse=True, params=ENGINES)
def engine(request: pytest.FixtureRequest) -> Iterator[str]:
    """Run every test in this file once per engine; run() picks it up."""
    global _engine
    _engine = request.param
    yield request.param


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """Local LA time on Nov `day`, 2026, as UTC."""
    return datetime(2026, 11, day, hour, minute, tzinfo=ZoneInfo(LA)).astimezone(UTC)


def window(day: int, start_hour: float, end_hour: float) -> Window:
    def moment(hour: float) -> datetime:
        return at(day, int(hour), round((hour % 1) * 60))

    return Window(moment(start_hour), moment(end_hour))


def task(title: str, minutes: int | None, windows: list[Window], **fields: Any) -> Item:
    return Item(title, FlexPreset.CUSTOM, windows=windows, estimate_min=minutes, **fields)


def run(items: list[Item], blocks: list[Block] = [], settings: SolverSettings = SETTINGS, **kw: Any) -> SolveResult:
    settings = replace(settings, engine=_engine)
    result = solve(items, blocks, [], kw.get("constraints", []), settings)
    assert_valid(result, items, blocks, settings)
    return result


def unplaced_of(result: SolveResult, items: list[Item]) -> dict[str, int]:
    """Minutes that didn't fit, by item title."""
    titles = {item.id: item.title for item in items}
    return {titles[u.item_id]: u.minutes for u in result.unplaced}


def placed_for(result: SolveResult, item: Item, blocks: list[Block] = []) -> list[Block]:
    kept_ids = {b.id for b in blocks if is_kept(b)}
    return [b for b in result.blocks if b.item_id == item.id and b.id not in kept_ids]


def assert_valid(result: SolveResult, items: list[Item], blocks: list[Block], settings: SolverSettings) -> None:
    """Check every hard constraint, plus totals and kept blocks."""
    slot = timedelta(minutes=settings.slot_min)
    zone = ZoneInfo(settings.timezone)
    by_item = {item.id: item for item in items}
    kept = [b for b in blocks if is_kept(b)]
    kept_ids = {b.id for b in kept}

    for b in kept:
        assert b in result.blocks, "kept block missing or changed"

    for b in result.blocks:
        if b.id in kept_ids:
            continue
        item = by_item[b.item_id]
        assert (b.start - datetime(1970, 1, 1, tzinfo=UTC)) % slot == timedelta(0), "off the slot grid"
        assert any(w.start <= b.start and b.end <= w.end for w in item.windows), "outside windows"
        assert item.deadline is None or b.end <= item.deadline, "misses deadline"

    ordered = sorted(result.blocks, key=lambda b: b.start)
    for first, second in zip(ordered, ordered[1:]):
        assert first.end <= second.start, "blocks overlap"

    for item in items:
        mine = [b for b in result.blocks if b.item_id == item.id]
        for dep_id in item.depends_on:
            for dep_block in (b for b in result.blocks if b.item_id == dep_id):
                assert all(dep_block.end <= b.start for b in mine), "dependency violated"
        if item.one_block_per_day:
            days = [b.start.astimezone(zone).date() for b in mine if b.id not in kept_ids or session_min(b) > 0]
            assert len(days) == len(set(days)), "two blocks on one day"
        if item.estimate_min is not None and item.windows:
            done = sum(covered_min(b) for b in kept if b.item_id == item.id)
            remaining = max(0, item.estimate_min - done)
            expected = -(-remaining // settings.slot_min) * settings.slot_min
            placed = sum((b.end - b.start) // timedelta(minutes=1) for b in mine if b.id not in kept_ids)
            missing = sum(u.minutes for u in result.unplaced if u.item_id == item.id)
            # Unplaced minutes are capped at the real remaining work, so 50 left on a
            # 15-minute grid is 60 placed or 50 unplaced.
            assert remaining <= placed + missing <= expected, "placed and unplaced time don't add up"
            assert placed == expected or missing > 0, "work left out but not reported"
    assert result.feasible == (not result.unplaced)


def test_single_item_takes_its_only_spot() -> None:
    gym = task("Gym", 60, [window(16, 9, 10)])
    [block] = run([gym]).blocks
    assert (block.start, block.end) == (at(16, 9), at(16, 10))


def test_two_items_share_a_window_without_overlap() -> None:
    a = task("A", 60, [window(16, 9, 11)])
    b = task("B", 60, [window(16, 9, 11)])
    assert run([a, b]).feasible


def test_plans_around_a_locked_block() -> None:
    lecture = task("Lecture", 60, [window(16, 9, 10)])
    locked = Block(lecture.id, at(16, 9), at(16, 10), locked=True)
    study = task("Study", 60, [window(16, 9, 11)])

    result = run([lecture, study], [locked])

    assert locked in result.blocks
    [block] = placed_for(result, study)
    assert (block.start, block.end) == (at(16, 10), at(16, 11))


def test_dependency_places_later_item_after() -> None:
    first = task("Outline", 60, [window(16, 9, 12)])
    second = task("Draft", 60, [window(16, 9, 12)], depends_on=[first.id])
    assert run([second, first]).feasible


def test_unmeetable_dependency_leaves_one_item_out() -> None:
    first = task("Outline", 60, [window(16, 9, 11)])
    second = task("Draft", 60, [window(16, 9, 10)], depends_on=[first.id])
    result = run([first, second])
    # Both can't fit in order: an hour of the two is left out, either one or split between them.
    assert (result.feasible, sum(unplaced_of(result, [first, second]).values())) == (False, 60)


def test_deadline_cuts_a_window_short() -> None:
    item = task("Problem set", 60, [window(16, 9, 12)], deadline=at(16, 10))
    [block] = run([item]).blocks
    assert (block.start, block.end) == (at(16, 9), at(16, 10))


def test_long_item_splits_into_chunks() -> None:
    code = task("Write code", 240, [window(16, 9, 17), window(17, 9, 17)], max_chunk_min=120)
    result = run([code])
    assert [b.end - b.start for b in result.blocks] == [timedelta(hours=2)] * 2


def test_uneven_work_splits_evenly_by_slots() -> None:
    code = task("Write code", 300, [window(16, 9, 17)], max_chunk_min=120)
    lengths = sorted((b.end - b.start) // timedelta(minutes=1) for b in run([code]).blocks)
    assert lengths == [90, 105, 105]


def test_one_block_per_day_spreads_sessions() -> None:
    gym = task("Gym", 120, [window(16, 9, 12), window(17, 9, 10)], max_chunk_min=60, one_block_per_day=True)
    blocks = run([gym]).blocks
    assert (blocks[1].start, blocks[1].end) == (at(17, 9), at(17, 10))


def test_one_block_per_day_can_leave_a_session_out() -> None:
    gym = task("Gym", 120, [window(16, 9, 12)], max_chunk_min=60, one_block_per_day=True)
    result = run([gym])
    assert (len(placed_for(result, gym)), unplaced_of(result, [gym])) == (1, {"Gym": 60})


def test_without_the_flag_blocks_may_share_a_day() -> None:
    pset = task("Problem set", 120, [window(16, 9, 11)], max_chunk_min=60)
    assert len(run([pset]).blocks) == 2


def test_same_local_day_even_when_utc_dates_differ() -> None:
    # 3pm PST is 23:00 UTC Monday; 6pm PST is 02:00 UTC Tuesday. Both are Monday locally.
    gym = task("Gym", 120, [window(16, 15, 16), window(16, 18, 19)], max_chunk_min=60, one_block_per_day=True)
    assert unplaced_of(run([gym]), [gym]) == {"Gym": 60}


def test_not_enough_time_places_what_fits() -> None:
    item = task("Essay", 180, [window(16, 9, 11)])
    result = run([item])
    [block] = result.blocks  # shortened from the end
    assert (block.start, block.end) == (at(16, 9), at(16, 11))
    assert (result.feasible, unplaced_of(result, [item])) == (False, {"Essay": 60})


def test_without_partial_nothing_is_placed() -> None:
    item = task("Essay", 180, [window(16, 9, 11)])
    result = solve([item], [], [], [], replace(SETTINGS, engine=_engine), partial=False)
    assert (result.feasible, result.blocks, result.status) == (False, [], "INFEASIBLE")
    assert unplaced_of(result, [item]) == {"Essay": 180}


def test_a_full_day_leaves_out_the_least_work() -> None:
    # 4h of work in a 3h morning: 1h is left out, wherever it comes from.
    a = task("Read", 120, [window(16, 9, 12)], max_chunk_min=60)
    b = task("Write", 120, [window(16, 9, 12)])
    result = run([a, b])
    assert sum(unplaced_of(result, [a, b]).values()) == 60


def test_partial_plan_keeps_out_of_kept_blocks_and_deadlines() -> None:
    lecture = task("Lecture", 60, [window(16, 9.5, 10.5)])
    locked = Block(lecture.id, at(16, 9, 30), at(16, 10, 30), locked=True)
    pset = task("Problem set", 180, [window(16, 9, 13)], deadline=at(16, 12))
    result = run([lecture, pset], [locked])
    [block] = placed_for(result, pset)
    assert (block.start, block.end) == (at(16, 10, 30), at(16, 12))  # the longer gap, before the deadline
    assert unplaced_of(result, [lecture, pset]) == {"Problem set": 90}


def test_partial_plan_respects_a_daily_limit() -> None:
    essay = task("Essay", 120, [window(16, 9, 12)])
    result = run([essay], constraints=[daily_limit(60)])
    assert (minutes_on(result, 16), unplaced_of(result, [essay])) == (60, {"Essay": 60})


def test_unplaced_minutes_are_capped_at_the_real_work_left() -> None:
    # 50 minutes is 4 slots, but nothing fits, so 50 minutes (not 60) didn't fit.
    item = task("Call", 50, [window(16, 9, 9.25)], deadline=at(16, 9))
    assert unplaced_of(run([item]), [item]) == {"Call": 50}


def test_a_week_that_fits_is_not_partial() -> None:
    item = task("Essay", 120, [window(16, 9, 11)])
    result = run([item])
    assert (result.feasible, result.unplaced) == (True, [])
    assert result.status in ("FOUND", "OPTIMAL")


def test_done_work_is_kept_and_reduces_what_is_placed() -> None:
    essay = task("Essay", 120, [window(16, 9, 12)])
    done = Block(essay.id, at(15, 9), at(15, 10), status=BlockStatus.DONE, actual_min=60)

    result = run([essay], [done])

    assert done in result.blocks
    [block] = placed_for(result, essay, [done])
    assert block.end - block.start == timedelta(hours=1)


def test_rescheduled_missed_work_is_placed_again() -> None:
    essay = task("Essay", 120, [window(16, 9, 12)])
    missed = Block(essay.id, at(15, 9), at(15, 10), status=BlockStatus.MISSED, missed_action=OnMiss.RESCHEDULE)

    [block] = placed_for(run([essay], [missed]), essay, [missed])

    assert block.end - block.start == timedelta(hours=2)


@pytest.mark.parametrize("action", [OnMiss.SKIP, OnMiss.CATCH_UP, None])
def test_skipped_caught_up_or_waiting_work_is_not_placed_again(action: OnMiss | None) -> None:
    essay = task("Essay", 120, [window(16, 9, 12)])
    missed = Block(essay.id, at(15, 9), at(15, 10), status=BlockStatus.MISSED, missed_action=action)

    [block] = placed_for(run([essay], [missed]), essay, [missed])

    assert block.end - block.start == timedelta(hours=1)


def test_a_partly_done_block_reschedules_only_the_rest() -> None:
    essay = task("Essay", 120, [window(16, 9, 12)])
    partly = Block(
        essay.id, at(15, 9), at(15, 11), status=BlockStatus.PARTIAL, actual_min=45, missed_action=OnMiss.RESCHEDULE
    )

    [block] = placed_for(run([essay], [partly]), essay, [partly])

    assert block.end - block.start == timedelta(minutes=75)


def test_a_skipped_session_leaves_its_day_free() -> None:
    gym = task("Gym", 120, [window(16, 9, 12), window(16, 14, 17)], max_chunk_min=60, one_block_per_day=True)
    skipped = Block(gym.id, at(16, 9), at(16, 10), status=BlockStatus.MISSED, missed_action=OnMiss.SKIP)

    [block] = placed_for(run([gym], [skipped]), gym, [skipped])

    assert block.start.astimezone(ZoneInfo(LA)).day == 16


def test_slot_size_is_a_setting() -> None:
    item = task("Read", 60, [window(16, 9.25, 10.75)])
    [block] = run([item], settings=SolverSettings(LA, slot_min=30)).blocks
    assert (block.start, block.end) == (at(16, 9, 30), at(16, 10, 30))


def test_item_without_estimate_fills_its_window() -> None:
    lecture = task("CS 70 lecture", None, [window(17, 11, 12.5)])
    [block] = run([lecture]).blocks
    assert (block.start, block.end) == (at(17, 11), at(17, 12, 30))


def test_item_without_windows_is_skipped() -> None:
    result = run([task("Email advisor", 15, [])])
    assert (result.feasible, result.blocks) == (True, [])


def test_unmoved_block_keeps_its_spot_and_id() -> None:
    item = task("Gym", 60, [window(16, 9, 12)])
    current = Block(item.id, at(16, 10), at(16, 11))
    [block] = run([item], [current]).blocks
    assert block == current


def test_re_solving_keeps_sessions_of_different_lengths_in_place() -> None:
    # 5h at a 2h max is 105, 105 and 90 min. The current plan put the 90 min
    # session first, so pairing old blocks with chunks by position would
    # stretch it to 105 min.
    item = task("Code", 300, [window(16, 9, 17), window(17, 9, 17), window(18, 9, 17)], max_chunk_min=120)
    current = [
        Block(item.id, at(16, 9), at(16, 10, 30)),  # 90 min
        Block(item.id, at(17, 9), at(17, 10, 45)),  # 105 min
        Block(item.id, at(18, 9), at(18, 10, 45)),  # 105 min
    ]
    assert run([item], current).blocks == current


def test_soft_constraints_are_ignored_and_hard_ones_rejected() -> None:
    item = task("Gym", 60, [window(16, 9, 10)])
    assert run([item], constraints=[Constraint(kind="buffer")]).feasible
    with pytest.raises(ValueError):
        run([item], constraints=[Constraint(kind="buffer", hard=True)])


MON = 0
SAT = 5


def daily_limit(max_min: int, weekdays: list[int] | None = None) -> Constraint:
    params: dict[str, Any] = {"max_min": max_min}
    if weekdays is not None:
        params["weekdays"] = weekdays
    return Constraint(kind="daily_limit", params=params, hard=True)


def minutes_on(result: SolveResult, day: int) -> int:
    start, end = at(day, 0), at(day + 1, 0)
    return sum((b.end - b.start) // timedelta(minutes=1) for b in result.blocks if start <= b.start < end)


def test_daily_limit_pushes_work_to_another_day() -> None:
    pset = task("Problem set", 120, [window(16, 9, 12), window(17, 9, 12)], max_chunk_min=60)
    result = run([pset], constraints=[daily_limit(60, [MON])])
    assert (minutes_on(result, 16), minutes_on(result, 17)) == (60, 60)


def test_daily_limit_counts_kept_blocks() -> None:
    lecture = task("Lecture", 120, [window(16, 9, 11)])
    locked = Block(lecture.id, at(16, 9), at(16, 11), locked=True)
    read = task("Read", 60, [window(16, 13, 15), window(17, 13, 15)])
    result = run([lecture, read], [locked], constraints=[daily_limit(120)])
    assert (minutes_on(result, 16), minutes_on(result, 17)) == (120, 60)


def test_kept_blocks_over_the_limit_only_close_that_day() -> None:
    lecture = task("Lecture", 180, [window(16, 9, 12)])
    locked = Block(lecture.id, at(16, 9), at(16, 12), locked=True)
    read = task("Read", 60, [window(16, 13, 15), window(17, 13, 15)])
    result = run([lecture, read], [locked], constraints=[daily_limit(120)])
    assert result.feasible
    assert minutes_on(result, 17) == 60


def test_daily_limit_only_applies_on_its_weekdays() -> None:
    pset = task("Problem set", 120, [window(16, 9, 12)], max_chunk_min=60)
    assert run([pset], constraints=[daily_limit(60, [SAT])]).feasible


def test_daily_limit_too_tight_is_not_feasible() -> None:
    essay = task("Essay", 120, [window(16, 9, 12)])
    assert not run([essay], constraints=[daily_limit(60)]).feasible


def test_inputs_are_not_mutated() -> None:
    item = task("Gym", 120, [window(16, 9, 12)], max_chunk_min=60)
    blocks = [Block(item.id, at(16, 9), at(16, 10)), Block(item.id, at(15, 9), at(15, 10), status=BlockStatus.MISSED)]
    before = copy.deepcopy(([item], blocks))
    run([item], blocks)
    assert ([item], blocks) == before


def test_status_says_how_the_search_ended() -> None:
    result = run([task("Gym", 60, [window(16, 9, 12)])])
    assert result.status == ("OPTIMAL" if _engine == "cp_sat" else "FOUND")
