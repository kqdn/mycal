import tomllib
from datetime import UTC, datetime
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


def test_infeasible_week_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = TINY.replace("estimate_min = 60", "estimate_min = 120")
    path = tmp_path / "week.toml"
    path.write_text(text, encoding="utf-8")
    assert main([str(path)]) == 1
    assert "No arrangement fits" in capsys.readouterr().out
