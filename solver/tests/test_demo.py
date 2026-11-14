import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from test_solve import assert_valid

from mycal.demo import Week, format_schedule, load_week, main, parse_week, plan_week

EXAMPLE = Path(__file__).parent.parent / "examples" / "week.toml"

TINY = """
timezone = "America/Los_Angeles"
week_start = 2026-11-16

[[work_frames]]
name = "Mornings"
weekdays = [0]
start_time = 09:00:00
end_time = 10:00:00

[[items]]
title = "Lecture"
preset = "exact"
start = 2026-11-17T11:00:00
end = 2026-11-17T12:30:00

[[items]]
title = "Gym"
preset = "day"
day = 2026-11-16
estimate_min = 60

[[items]]
title = "Email advisor"
preset = "custom"
windows = []
estimate_min = 15
"""


def week_from(text: str) -> Week:
    return parse_week(tomllib.loads(text))


def test_example_week_solves() -> None:
    week = load_week(EXAMPLE)
    items, result = plan_week(week)
    assert result.feasible
    assert_valid(result, items, [], week.settings)


def test_schedule_text() -> None:
    week = week_from(TINY)
    items, result = plan_week(week)
    assert format_schedule(items, result, week.settings.timezone) == (
        "Mon Nov 16\n"
        "  09:00-10:00  Gym\n"
        "\n"
        "Tue Nov 17\n"
        "  11:00-12:30  Lecture\n"
        "\n"
        "Unscheduled\n"
        "  Email advisor"
    )


def test_local_times_become_utc() -> None:
    lecture = week_from(TINY).items[0]
    assert lecture.preset_params["start"] == datetime(2026, 11, 17, 19, tzinfo=UTC)


def test_depends_on_uses_titles() -> None:
    text = TINY + '\n[[items]]\ntitle = "Notes"\npreset = "day"\nday = 2026-11-16\ndepends_on = ["Gym"]\n'
    week = week_from(text)
    assert week.items[3].depends_on == [week.items[1].id]


def test_unknown_dependency_rejected() -> None:
    text = TINY + '\n[[items]]\ntitle = "Notes"\npreset = "day"\nday = 2026-11-16\ndepends_on = ["Nope"]\n'
    with pytest.raises(ValueError, match="Nope"):
        week_from(text)


def test_duplicate_titles_rejected() -> None:
    text = TINY + '\n[[items]]\ntitle = "Gym"\npreset = "day"\nday = 2026-11-18\n'
    with pytest.raises(ValueError, match="Duplicate"):
        week_from(text)


def test_unknown_param_rejected() -> None:
    text = TINY + '\n[[items]]\ntitle = "Run"\npreset = "day"\nday = 2026-11-18\nweekday = 2\n'
    with pytest.raises(ValueError, match="weekday"):
        week_from(text)


SERIES = """
[[series]]
title = "Seminar"
rrule = "FREQ=WEEKLY;BYDAY=WE"
start_date = 2026-09-02
preset = "exact"
start_time = 14:00:00
end_time = 15:00:00
"""


def test_series_occurrences_are_scheduled() -> None:
    week = week_from(TINY + SERIES)
    items, result = plan_week(week)
    [seminar] = [i for i in items if i.title == "Seminar"]
    assert (seminar.series_id, seminar.occurrence_date) == (week.series[0].id, date(2026, 11, 18))
    assert "Wed Nov 18\n  14:00-15:00  Seminar" in format_schedule(items, result, week.settings.timezone)


def test_series_skipped_date_is_not_scheduled() -> None:
    week = week_from(TINY + SERIES + "skipped_dates = [2026-11-18]\n")
    items, _ = plan_week(week)
    assert all(i.title != "Seminar" for i in items)


def test_series_end_given_twice_rejected() -> None:
    text = TINY + SERIES.replace("BYDAY=WE", "BYDAY=WE;COUNT=5") + "end_date = 2026-12-31\n"
    with pytest.raises(ValueError, match="Seminar"):
        week_from(text)


def test_constraints_are_read_and_applied() -> None:
    limit = '\n[[constraints]]\nkind = "daily_limit"\nhard = true\nmax_min = 30\nweekdays = [0]\n'
    week = week_from(TINY + limit)
    assert week.constraints[0].params == {"max_min": 30, "weekdays": [0]}
    _, result = plan_week(week)
    assert not result.feasible  # the 60-minute Monday gym session no longer fits


PREFER = """
[[constraints]]
kind = "time_preference"
items = ["Gym", "Seminar"]
mode = "avoid"
weekdays = [0]
start_time = 09:00:00
end_time = 09:30:00
weight = 2
"""


def test_constraint_items_become_item_and_series_ids() -> None:
    week = week_from(TINY + SERIES + PREFER)
    [pref] = week.constraints
    assert pref.params["item_ids"] == [week.items[1].id]
    assert pref.params["series_ids"] == [week.series[0].id]
    assert pref.weight == 2
    _, result = plan_week(week)  # local times compile to windows before solving
    assert result.feasible


def test_constraint_with_unknown_item_rejected() -> None:
    with pytest.raises(ValueError, match="Nope"):
        week_from(TINY + PREFER.replace('"Seminar"', '"Nope"'))


def test_infeasible_week_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = TINY.replace("estimate_min = 60", "estimate_min = 120")
    path = tmp_path / "week.toml"
    path.write_text(text, encoding="utf-8")
    assert main([str(path)]) == 1
    assert "No arrangement fits" in capsys.readouterr().out
