"""CP-SAT score tests. Each case has one best answer, so exact positions are asserted."""

from datetime import timedelta

from test_solve import LA, assert_valid, at, task, window

from mycal import Block, Item, SolveResult, SolverSettings, solve

CP_SAT = SolverSettings(timezone=LA, engine="cp_sat")


def run(items: list[Item], blocks: list[Block] = []) -> SolveResult:
    result = solve(items, blocks, [], [], CP_SAT)
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


def test_busiest_day_is_kept_light() -> None:
    lab = task("Lab", 60, [window(16, 9, 10)])
    essay = task("Essay", 60, [window(16, 10, 12), window(17, 9, 11)])
    result = run([lab, essay])
    [essay_block] = [b for b in result.blocks if b.item_id == essay.id]
    assert (essay_block.start, essay_block.end) == (at(17, 9), at(17, 10))


def test_stability_beats_balance() -> None:
    lab = task("Lab", 60, [window(16, 9, 10)])
    essay = task("Essay", 60, [window(16, 10, 12), window(17, 9, 11)])
    current = Block(essay.id, at(16, 10), at(16, 11))
    result = run([lab, essay], [current])
    assert current in result.blocks


def test_kept_blocks_count_toward_a_days_load() -> None:
    lecture = task("Lecture", None, [window(16, 9, 12)])
    locked = Block(lecture.id, at(16, 9), at(16, 12), locked=True)
    read = task("Read", 60, [window(16, 13, 15), window(17, 13, 15)])
    result = run([lecture, read], [locked])
    [block] = [b for b in result.blocks if b.item_id == read.id]
    assert block.start == at(17, 13)
    assert block.end - block.start == timedelta(hours=1)
