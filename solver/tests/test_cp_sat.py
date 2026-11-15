"""CP-SAT score tests.

With no earliness slack each case has one best answer, so exact positions are
asserted. The huge-slack tests check only the higher-tier outcome, since the
slack lets the lowest tier (earliness) move.
"""

from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from test_solve import LA, assert_valid, at, task, window

from mycal import Block, BlockStatus, Constraint, Item, SolveResult, SolverSettings, Window, WorkFrame, solve
from mycal.cp_sat import build_model, tier_weights
from mycal.problem import build_problem, floor_slot
from ortools.sat.python import cp_model

CP_SAT = SolverSettings(timezone=LA, engine="cp_sat", earliness_slack_min=0)
HUGE_SLACK = SolverSettings(timezone=LA, engine="cp_sat", earliness_slack_min=600)
MON, TUE, SAT = 0, 1, 5
MON_TUE = WorkFrame("Mon-Tue", [MON, TUE], time(9), time(17), LA)


def run(
    items: list[Item],
    blocks: list[Block] = [],
    frames: list[WorkFrame] = [MON_TUE],
    constraints: list[Constraint] = [],
    settings: SolverSettings = CP_SAT,
) -> SolveResult:
    result = solve(items, blocks, frames, constraints, settings)
    assert result.feasible
    assert_valid(result, items, blocks, settings)
    return result


def spans(result: SolveResult) -> list[tuple]:
    return [(b.start, b.end) for b in result.blocks]


def test_blocks_start_early_in_the_day() -> None:
    item = task("Read", 60, [window(16, 9, 12)])
    assert spans(run([item])) == [(at(16, 9), at(16, 10))]


def test_an_items_blocks_spread_across_days() -> None:
    pset = task("Problem set", 120, [window(16, 9, 11), window(17, 9, 11)], max_chunk_min=60)
    assert spans(run([pset])) == [(at(16, 9), at(16, 10)), (at(17, 9), at(17, 10))]


def test_overnight_frame_prefers_its_start_over_midnight() -> None:
    # Mon 10pm to Tue 2am. Counting from local midnight would pick Tue 12am.
    late = Window(at(16, 22), at(17, 2))
    item = task("Read", 60, [late])
    assert spans(run([item])) == [(at(16, 22), at(16, 23))]


def test_frame_counts_from_its_real_start_before_the_window() -> None:
    # Sun 8pm to Mon 2am frames, but the item may only start from Mon 12am, as
    # when Sunday's frame runs into the planning week. Mon 12am is still late
    # in that frame, so Mon 8pm wins.
    nights = WorkFrame("Nights", [6, MON], time(20), time(2), LA)
    item = task("Read", 60, [Window(at(16, 0), at(16, 2)), window(16, 20, 23)])
    assert spans(run([item], frames=[nights])) == [(at(16, 20), at(16, 21))]


# In the balance tests, Monday is at least as early in its window as Tuesday,
# so landing on Tuesday shows balance at work.


def test_fullest_day_is_kept_light() -> None:
    lab = task("Lab", 60, [window(16, 9, 10)])
    essay = task("Essay", 60, [window(16, 10, 12), window(17, 11, 13)])
    result = run([lab, essay])
    [essay_block] = [b for b in result.blocks if b.item_id == essay.id]
    assert (essay_block.start, essay_block.end) == (at(17, 11), at(17, 12))


def test_stability_beats_balance() -> None:
    lab = task("Lab", 60, [window(16, 9, 10)])
    essay = task("Essay", 60, [window(16, 10, 12), window(17, 11, 13)])
    current = Block(essay.id, at(16, 10), at(16, 11))
    result = run([lab, essay], [current])
    assert current in result.blocks


def test_kept_blocks_count_toward_a_days_load() -> None:
    lecture = task("Lecture", None, [window(16, 9, 12)])
    locked = Block(lecture.id, at(16, 9), at(16, 12), locked=True)
    read = task("Read", 60, [window(16, 13, 15), window(17, 14, 16)])
    result = run([lecture, read], [locked])
    [block] = [b for b in result.blocks if b.item_id == read.id]
    assert block.start == at(17, 14)
    assert block.end - block.start == timedelta(hours=1)


def test_balance_is_relative_to_each_days_work_frame() -> None:
    # Mon has a 9h frame, Sat a 6h one. 5h of work splits 3h + 2h, so both days
    # are a third full. Balancing raw hours would favor 2h + 3h here, since
    # Saturday's frame starts earlier in the day.
    weekday = WorkFrame("Weekday", [MON], time(9), time(18), LA)
    weekend = WorkFrame("Weekend", [SAT], time(8), time(14), LA)
    code = task("Write code", 300, [window(16, 9, 18), window(21, 8, 14)], max_chunk_min=60)

    result = run([code], frames=[weekday, weekend])

    monday = [b for b in result.blocks if b.start < at(17, 0)]
    assert (len(monday), len(result.blocks) - len(monday)) == (3, 2)


def preference(windows: list[Window], items: list[Item] = [], mode: str = "prefer") -> Constraint:
    params = {"windows": windows, "mode": mode, "item_ids": [item.id for item in items]}
    return Constraint(kind="time_preference", params=params)


def test_preference_moves_a_block_into_its_range() -> None:
    read = task("Read", 60, [window(16, 9, 17)])
    afternoon = preference([window(16, 14, 16)], [read])
    assert spans(run([read], constraints=[afternoon])) == [(at(16, 14), at(16, 15))]


def test_avoid_keeps_a_block_out_of_its_range() -> None:
    read = task("Read", 60, [window(16, 9, 12)])
    morning = preference([window(16, 9, 11)], [read], mode="avoid")
    assert spans(run([read], constraints=[morning])) == [(at(16, 11), at(16, 12))]


def test_a_block_that_cannot_fit_gets_as_close_as_it_can() -> None:
    # 2h block, preferred 4pm to 6pm, but the window ends at 5pm.
    code = task("Code", 120, [window(16, 9, 17)])
    late = preference([window(16, 16, 18)], [code])
    assert spans(run([code], constraints=[late])) == [(at(16, 15), at(16, 17))]


def test_preference_applies_only_to_its_items() -> None:
    gym = task("Gym", 60, [window(16, 9, 17)])
    read = task("Read", 60, [window(16, 9, 17)])
    result = run([gym, read], constraints=[preference([window(16, 14, 17)], [gym])])
    blocks = {b.item_id: (b.start, b.end) for b in result.blocks}
    assert blocks[gym.id] == (at(16, 14), at(16, 15))
    assert blocks[read.id] == (at(16, 9), at(16, 10))


def test_preference_beats_balance() -> None:
    # Same week as test_fullest_day_is_kept_light, where balance alone picks Tuesday.
    lab = task("Lab", 60, [window(16, 9, 10)])
    essay = task("Essay", 60, [window(16, 10, 12), window(17, 11, 13)])
    result = run([lab, essay], constraints=[preference([window(16, 10, 12)], [essay])])
    [essay_block] = [b for b in result.blocks if b.item_id == essay.id]
    assert (essay_block.start, essay_block.end) == (at(16, 10), at(16, 11))


def test_spread_beats_preference() -> None:
    # Both hours fit in Monday's preferred range, but spreading wins.
    pset = task("Problem set", 120, [window(16, 9, 11), window(17, 9, 11)], max_chunk_min=60)
    monday = preference([window(16, 9, 11)], [pset])
    assert spans(run([pset], constraints=[monday])) == [(at(16, 9), at(16, 10)), (at(17, 9), at(17, 10))]


def test_heavier_preference_wins() -> None:
    read = task("Read", 60, [window(16, 9, 17)])
    morning = preference([window(16, 9, 10)], [read])
    afternoon = preference([window(16, 15, 16)], [read])
    afternoon.weight = 2
    assert spans(run([read], constraints=[morning, afternoon])) == [(at(16, 15), at(16, 16))]


EVERY_DAY = WorkFrame("Every day", list(range(7)), time(9), time(17), LA)


def rest(items: list[Item] = [], min_gap_days: int = 1, series_ids: list = []) -> Constraint:
    params = {"min_gap_days": min_gap_days, "item_ids": [i.id for i in items], "series_ids": series_ids}
    return Constraint(kind="rest_between", params=params)


def gym(days: range, minutes: int = 180, **fields) -> Item:
    return task("Gym", minutes, [window(d, 9, 17) for d in days], max_chunk_min=60, one_block_per_day=True, **fields)


def session_days(result: SolveResult, item: Item) -> list[int]:
    return sorted(b.start.astimezone(ZoneInfo(LA)).day for b in result.blocks if b.item_id == item.id)


def test_sessions_leave_a_rest_day_between() -> None:
    item = gym(range(16, 21))  # Mon to Fri: only Mon, Wed, Fri leaves rest days
    result = run([item], frames=[EVERY_DAY], constraints=[rest([item])])
    assert session_days(result, item) == [16, 18, 20]


def test_longer_gap() -> None:
    item = gym(range(16, 20), minutes=120)  # Mon to Thu, two free days wanted
    result = run([item], frames=[EVERY_DAY], constraints=[rest([item], min_gap_days=2)])
    assert session_days(result, item) == [16, 19]


def test_done_session_counts_toward_the_gaps() -> None:
    # Gym moved to Tuesday this week and is done; the other two space around it.
    item = gym(range(16, 23))
    done = Block(item.id, at(17, 9), at(17, 10), status=BlockStatus.DONE, actual_min=60)
    result = run([item], [done], frames=[EVERY_DAY], constraints=[rest([item])])
    days = session_days(result, item)
    assert 17 in days and len(days) == 3
    assert all(b - a >= 2 for a, b in zip(days, days[1:]))


def test_back_to_back_is_allowed_when_nothing_else_fits() -> None:
    item = gym(range(16, 18), minutes=120)  # only Mon and Tue
    result = run([item], frames=[EVERY_DAY], constraints=[rest([item])])
    assert session_days(result, item) == [16, 17]


def test_rest_between_covers_series_occurrences() -> None:
    series_id = uuid4()
    item = gym(range(16, 21), series_id=series_id, occurrence_date=date(2026, 11, 16))
    result = run([item], frames=[EVERY_DAY], constraints=[rest(series_ids=[series_id])])
    assert session_days(result, item) == [16, 18, 20]


def test_a_block_in_any_preferred_range_has_no_penalty() -> None:
    # Preferred 6-7pm or 9-10pm; 6pm is taken, so 9pm wins over the earlier 7pm.
    gym_item = task("Gym", 60, [window(16, 17, 23)])
    lecture = task("Lecture", None, [window(16, 18, 19)])
    locked = Block(lecture.id, at(16, 18), at(16, 19), locked=True)
    evenings = preference([window(16, 18, 19), window(16, 21, 22)], [gym_item])
    result = run([gym_item, lecture], [locked], constraints=[evenings])
    [block] = [b for b in result.blocks if b.item_id == gym_item.id]
    assert (block.start, block.end) == (at(16, 21), at(16, 22))


# Slack: only the lowest tier may come out worse. With 600 minutes of slack per
# block, each higher tier still wins its trade end to end, including against
# every tier below it. The worst case for the weights is checked at the model
# level further down.


def blocks_of(result: SolveResult, item: Item) -> list[Block]:
    return [b for b in result.blocks if b.item_id == item.id]


def test_slack_keeps_balance_over_earliness() -> None:
    # Monday 10am is 8 slots earlier in the frame than Tuesday 12pm, but
    # Monday already has the lab, so balance wants Tuesday.
    lab = task("Lab", 60, [window(16, 9, 10)])
    essay = task("Essay", 60, [window(16, 9, 12), window(17, 12, 13)])
    for settings in (CP_SAT, HUGE_SLACK):
        [block] = blocks_of(run([lab, essay], settings=settings), essay)
        assert block.start == at(17, 12)


def test_slack_keeps_stability_over_balance() -> None:
    lab = task("Lab", 60, [window(16, 9, 10)])
    essay = task("Essay", 60, [window(16, 10, 12), window(17, 11, 13)])
    current = Block(essay.id, at(16, 10), at(16, 11))
    assert current in run([lab, essay], [current], settings=HUGE_SLACK).blocks


def test_slack_keeps_preference_over_balance() -> None:
    lab = task("Lab", 60, [window(16, 9, 10)])
    essay = task("Essay", 60, [window(16, 10, 12), window(17, 11, 13)])
    result = run([lab, essay], constraints=[preference([window(16, 10, 12)], [essay])], settings=HUGE_SLACK)
    [block] = blocks_of(result, essay)
    assert at(16, 10) <= block.start and block.end <= at(16, 12)


def test_slack_keeps_spread_over_every_lower_tier() -> None:
    # Two hours fit on Monday morning, where the preference, balance and
    # earliness all want them. Spreading puts one on Tuesday at 3pm instead:
    # outside the preference, on the later day, 24 slots into the frame.
    pset = task("Problem set", 120, [window(16, 9, 11), window(17, 15, 17)], max_chunk_min=60)
    monday = preference([window(16, 9, 11)], [pset])
    result = run([pset], constraints=[monday], settings=HUGE_SLACK)
    assert sorted(b.start.astimezone(ZoneInfo(LA)).day for b in blocks_of(result, pset)) == [16, 17]


@pytest.mark.parametrize("slack", [0, 4, 100])
@pytest.mark.parametrize("max_totals", [[10, 3, 7, 2, 5], [0, 0, 0, 0, 0], [96, 1000, 2400, 8, 8]])
def test_each_tier_outweighs_everything_below_it_plus_slack(max_totals: list[int], slack: int) -> None:
    weights = tier_weights(max_totals, slack)
    assert weights[0] == 1
    for k in range(1, len(weights)):
        lower = sum(w * m for w, m in zip(weights[:k], max_totals[:k]))
        assert weights[k] >= lower + slack + 1


def test_same_input_gives_the_same_plan() -> None:
    items = [gym(range(16, 21)), task("Read", 120, [window(16, 9, 17), window(17, 9, 17)], max_chunk_min=60)]
    first, second = (run(items, frames=[EVERY_DAY], settings=s) for s in (HUGE_SLACK, HUGE_SLACK))
    assert [(b.item_id, b.start, b.end) for b in first.blocks] == [(b.item_id, b.start, b.end) for b in second.blocks]
    assert first.status == second.status


# The gap limit at the model level. The tests above would pass even with wrong
# weights: on weeks this small CP-SAT proves the exact optimum before the gap
# limit matters, and ordinary trades gain far less below than the weights
# allow for. This one is the worst case the weights must survive: being worse
# by the smallest possible step in balance (1 unit) while gaining the largest
# possible amount in earliness (the item's whole offset range).


def optimum(model: cp_model.CpModel) -> float:
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    assert solver.solve(model) == cp_model.OPTIMAL
    return solver.objective_value


def forced_penalty(
    items: list[Item], forced: tuple[Item, datetime], frames: list[WorkFrame]
) -> tuple[float, int]:
    """How much worse the best plan with `forced`'s start scores than the best plan, and the slack."""
    problem = build_problem(items, [], [], HUGE_SLACK, frames)
    built = build_model(problem)
    assert built is not None
    best = optimum(built.model)
    model = built.model.clone()
    item, start = forced
    i = next(i for i, c in enumerate(problem.chunks) if c.item_id == item.id)
    model.add(model.get_int_var_from_proto_index(built.starts[i].index) == floor_slot(start, HUGE_SLACK.slot_min))
    return optimum(model) - best, built.slack


def test_one_unit_worse_balance_stays_outside_the_gap_even_with_all_earliness_gained() -> None:
    # Monday's frame is 7h45m and Tuesday's 8h, so 15 minutes fills Monday to
    # 33 thousandths and Tuesday to 32: one unit apart. Monday 9:00 is the
    # earliest start (offset 0), Tuesday 16:45 the latest (offset 31, the max).
    monday = WorkFrame("Mon", [MON], time(9), time(16, 45), LA)
    tuesday = WorkFrame("Tue", [TUE], time(9), time(17), LA)
    essay = task("Essay", 15, [window(16, 9, 9.25), window(17, 16.75, 17)])
    penalty, slack = forced_penalty([essay], (essay, at(16, 9)), [monday, tuesday])
    assert slack == 600 // 15
    assert penalty == slack + 1  # just outside the gap limit
