"""Fixed events (items with no estimate) keep their real times, even off the slot grid.

Berkeley classes start at :10. A fixed event is never moved or rounded; other
work stays off every slot it touches. Fixed events may overlap each other
and kept blocks (double booking); solve() plans them and reports each overlap.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from mycal import Block, Constraint, FlexPreset, Item, SolveResult, SolverSettings, Window, solve

LA = "America/Los_Angeles"
ENGINES = ["backtracking", "cp_sat"]


def at(hour: int, minute: int = 0) -> datetime:
    """Tue Nov 17, 2026, local LA time, as UTC."""
    return datetime(2026, 11, 17, hour, minute, tzinfo=ZoneInfo(LA)).astimezone(UTC)


def event(title: str, start: datetime, end: datetime) -> Item:
    return Item(title, FlexPreset.CUSTOM, windows=[Window(start, end)])


def work(minutes: int) -> Item:
    return Item("Work", FlexPreset.CUSTOM, windows=[Window(at(9), at(11))], estimate_min=minutes)


def run(engine: str, items: list[Item], blocks: list[Block] = [], constraints: list[Constraint] = []) -> SolveResult:
    return solve(items, blocks, [], constraints, SolverSettings(LA, engine=engine))  # type: ignore[arg-type]


def times(result: SolveResult, item: Item) -> list[tuple[datetime, datetime]]:
    return [(b.start, b.end) for b in result.blocks if b.item_id == item.id]


@pytest.mark.parametrize("engine", ENGINES)
def test_a_class_at_ten_past_keeps_its_real_times_and_its_whole_slot(engine: str) -> None:
    lecture, homework = event("Class", at(9, 10), at(10)), work(60)

    result = run(engine, [lecture, homework])

    assert result.feasible
    assert times(result, lecture) == [(at(9, 10), at(10))]
    assert times(result, homework) == [(at(10), at(11))]  # 9:00 to 9:10 shares the class's slot


@pytest.mark.parametrize("engine", ENGINES)
def test_a_ten_minute_event_off_the_grid_still_plans(engine: str) -> None:
    short = event("Office hours", at(9, 10), at(9, 20))

    result = run(engine, [short, work(60)])

    assert result.feasible
    assert times(result, short) == [(at(9, 10), at(9, 20))]


@pytest.mark.parametrize("engine", ENGINES)
def test_back_to_back_fixed_events_sharing_a_slot_still_plan(engine: str) -> None:
    first, second = event("Quiz", at(9), at(9, 10)), event("Class", at(9, 10), at(10))

    result = run(engine, [first, second, work(60)])

    assert result.feasible
    assert times(result, first) == [(at(9), at(9, 10))]
    assert times(result, second) == [(at(9, 10), at(10))]


@pytest.mark.parametrize("engine", ENGINES)
def test_fixed_events_that_really_overlap_both_plan_and_are_reported(engine: str) -> None:
    quiz, lecture, homework = event("Quiz", at(9), at(9, 40)), event("Class", at(9, 30), at(10)), work(60)

    result = run(engine, [quiz, lecture, homework])

    assert result.feasible
    assert times(result, quiz) == [(at(9), at(9, 40))]
    assert times(result, lecture) == [(at(9, 30), at(10))]
    assert times(result, homework) == [(at(10), at(11))]  # flexible work still stays clear of both
    [(first, second)] = result.overlaps
    by_id = {b.id: b.item_id for b in result.blocks}
    assert (by_id[first], by_id[second]) == (quiz.id, lecture.id)


@pytest.mark.parametrize("engine", ENGINES)
def test_a_fixed_event_over_a_locked_block_plans_and_is_reported(engine: str) -> None:
    homework = work(60)
    locked = Block(homework.id, at(9), at(10), locked=True)
    lecture = event("Class", at(9, 30), at(10, 30))

    result = run(engine, [homework, lecture], [locked])

    assert result.feasible
    assert times(result, homework) == [(at(9), at(10))]
    assert result.overlaps == [(locked.id, next(b.id for b in result.blocks if b.item_id == lecture.id))]


@pytest.mark.parametrize("engine", ENGINES)
def test_events_that_only_share_a_slot_are_not_an_overlap(engine: str) -> None:
    result = run(engine, [event("Quiz", at(9), at(9, 10)), event("Class", at(9, 10), at(10))])

    assert result.overlaps == []


@pytest.mark.parametrize("engine", ENGINES)
def test_solve_returns_a_fixed_event_unchanged_and_keeps_it_on_re_solve(engine: str) -> None:
    lecture = event("Class", at(9, 10), at(10))

    [first] = run(engine, [lecture]).blocks
    [again] = run(engine, [lecture], [first]).blocks  # the current plan goes back in

    assert (first.item_id, first.start, first.end) == (lecture.id, at(9, 10), at(10))
    assert again == first


@pytest.mark.parametrize("engine", ENGINES)
def test_a_daily_limit_counts_a_fixed_event_by_its_real_minutes(engine: str) -> None:
    limit = Constraint(kind="daily_limit", hard=True, params={"max_min": 110})

    result = run(engine, [event("Class", at(9, 10), at(10)), work(60)], constraints=[limit])

    assert result.feasible  # 50 + 60 fits in 110; counted as a whole hour it wouldn't

