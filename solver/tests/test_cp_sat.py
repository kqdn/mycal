"""CP-SAT score tests. Each case has one best answer, so exact positions are asserted."""

from datetime import time, timedelta

from test_solve import LA, assert_valid, at, task, window

from mycal import Block, Constraint, Item, SolveResult, SolverSettings, Window, WorkFrame, solve

CP_SAT = SolverSettings(timezone=LA, engine="cp_sat")
MON, TUE, SAT = 0, 1, 5
MON_TUE = WorkFrame("Mon-Tue", [MON, TUE], time(9), time(17), LA)


def run(
    items: list[Item],
    blocks: list[Block] = [],
    frames: list[WorkFrame] = [MON_TUE],
    constraints: list[Constraint] = [],
) -> SolveResult:
    result = solve(items, blocks, frames, constraints, CP_SAT)
    assert result.feasible
    assert_valid(result, items, blocks, CP_SAT)
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
