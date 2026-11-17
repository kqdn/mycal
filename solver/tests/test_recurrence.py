"""Series expansion and RRULE parsing. Week of Mon Nov 16, 2026 in Los Angeles unless noted."""

from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mycal import FlexPreset, Item, ItemTemplate, Rule, Series, SolverSettings, WorkFrame, compile_windows, solve
from mycal.recurrence import (
    expand_series,
    occurrence_dates,
    rule_to_rrule,
    series_rule_from_rrule,
    skip_occurrence,
)

LA = "America/Los_Angeles"
MON, TUE, WED, THU, FRI = 0, 1, 2, 3, 4
LECTURE = ItemTemplate(FlexPreset.EXACT, {"start_time": time(9), "end_time": time(10, 30)}, checkable=True)


def NOV(day: int) -> date:
    return date(2026, 11, day)


def series(rule: Rule, template: ItemTemplate = LECTURE, **fields: Any) -> Series:
    return Series("Lecture", rule, LA, fields.pop("start_date", NOV(16)), template, **fields)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# Occurrence dates


def test_daily_every_two_days() -> None:
    s = series(Rule("daily", interval=2))
    assert occurrence_dates(s, NOV(16), NOV(22)) == [NOV(16), NOV(18), NOV(20), NOV(22)]


def test_weekly_on_chosen_days() -> None:
    s = series(Rule("weekly", weekdays=[MON, WED]))
    assert occurrence_dates(s, NOV(16), NOV(22)) == [NOV(16), NOV(18)]


def test_every_two_weeks_counts_monday_weeks_from_start() -> None:
    # Starts on a Wednesday: its week (from Mon Nov 16) is week 0, so Thu Nov 19
    # counts but Mon Nov 16 is before the start. Week 1 is off; week 2 is on.
    s = series(Rule("weekly", interval=2, weekdays=[MON, THU]), start_date=NOV(18))
    assert occurrence_dates(s, NOV(16), date(2026, 12, 6)) == [NOV(19), NOV(30), date(2026, 12, 3)]


def test_bounds_and_skipped_dates() -> None:
    s = series(
        Rule("weekly", weekdays=[MON]),
        start_date=NOV(23),
        end_date=date(2026, 12, 7),
        skipped_dates=[NOV(30)],
    )
    assert occurrence_dates(s, date(2026, 11, 1), date(2026, 12, 31)) == [NOV(23), date(2026, 12, 7)]


# Expansion


def test_exact_occurrences_keep_local_time_across_dst() -> None:
    s = series(Rule("weekly", weekdays=[MON]), start_date=date(2027, 3, 1))
    items = expand_series(s, [], date(2027, 3, 8), date(2027, 3, 15))
    assert [(i.preset_params["start"], i.preset_params["end"]) for i in items] == [
        (utc(2027, 3, 8, 17), utc(2027, 3, 8, 18, 30)),  # 9am PST
        (utc(2027, 3, 15, 16), utc(2027, 3, 15, 17, 30)),  # 9am PDT
    ]


def test_occurrence_copies_template_and_links_to_series() -> None:
    s = series(Rule("weekly", weekdays=[TUE]))
    [item] = expand_series(s, [], NOV(16), NOV(22))
    assert (item.title, item.series_id, item.occurrence_date) == ("Lecture", s.id, NOV(17))
    assert item.checkable and item.flex_preset is FlexPreset.EXACT


def test_day_preset_gets_the_occurrence_date() -> None:
    lab = ItemTemplate(FlexPreset.DAY, estimate_min=120)
    [item] = expand_series(series(Rule("weekly", weekdays=[WED]), lab), [], NOV(16), NOV(22))
    assert item.preset_params == {"day": NOV(18)}
    assert item.estimate_min == 120


def test_deadline_time_lands_on_the_occurrence_date() -> None:
    pset = ItemTemplate(FlexPreset.BEFORE_DEADLINE, estimate_min=240, deadline_time=time(17))
    [item] = expand_series(series(Rule("weekly", weekdays=[FRI]), pset), [], NOV(16), NOV(22))
    assert item.deadline == utc(2026, 11, 21, 1)  # Fri 5pm PST


def test_every_day_template_gets_the_occurrence_week() -> None:
    piano = ItemTemplate(
        FlexPreset.DAYS,
        {"weekdays": [MON, TUE, WED, THU, FRI], "every_day": True, "session_min": 30},
        estimate_min=150,
        max_chunk_min=30,
        one_block_per_day=True,
    )
    [item] = expand_series(series(Rule("weekly", weekdays=[MON]), piano), [], NOV(16), NOV(22))
    assert item.preset_params == {
        "weekdays": [MON, TUE, WED, THU, FRI],
        "every_day": True,
        "session_min": 30,
        "week": NOV(16),
    }


def test_expanding_twice_creates_nothing_new() -> None:
    s = series(Rule("weekly", weekdays=[TUE, THU]))
    first = expand_series(s, [], NOV(16), NOV(22))
    assert len(first) == 2
    assert expand_series(s, first, NOV(16), NOV(22)) == []


def test_editing_the_template_only_reaches_future_occurrences() -> None:
    s = series(Rule("weekly", weekdays=[WED]), ItemTemplate(FlexPreset.DAY, estimate_min=60))
    [this_week] = expand_series(s, [], NOV(16), NOV(22))
    s.template.estimate_min = 90
    [next_week] = expand_series(s, [this_week], NOV(16), NOV(29))
    assert (this_week.estimate_min, next_week.estimate_min) == (60, 90)


def test_skipped_occurrence_is_not_created() -> None:
    s = series(Rule("weekly", weekdays=[TUE, THU]))
    skipped = skip_occurrence(s, NOV(19))
    assert s.skipped_dates == []
    assert [i.occurrence_date for i in expand_series(skipped, [], NOV(16), NOV(22))] == [NOV(17)]


def test_weekly_gym_occurrence_compiles_and_solves() -> None:
    # "3 times a week": one occurrence per week, anchored on Monday.
    gym = ItemTemplate(
        FlexPreset.DAYS, {"weekdays": [MON, WED, FRI]}, estimate_min=180, max_chunk_min=60, one_block_per_day=True
    )
    frame = WorkFrame("Weekdays", [MON, TUE, WED, THU, FRI], time(9), time(18), LA)
    [item] = expand_series(series(Rule("weekly", weekdays=[MON]), gym), [], NOV(16), NOV(22))
    assert item.preset_params["week"] == NOV(16)
    start, end = utc(2026, 11, 16, 8), utc(2026, 11, 23, 8)
    item.windows = compile_windows(item, [frame], LA, start, end)

    result = solve([item], [], [frame], [], SolverSettings(LA))

    assert result.feasible
    assert sorted(b.start.astimezone(ZoneInfo(LA)).weekday() for b in result.blocks) == [MON, WED, FRI]


# Validation


@pytest.mark.parametrize(
    ("preset", "params", "fields"),
    [
        (FlexPreset.CUSTOM, {"windows": []}, {}),
        (FlexPreset.DAY_RANGE, {"start_time": time(9)}, {}),
        (FlexPreset.DAYS, {"weekdays": [MON], "day": NOV(16)}, {}),
        (FlexPreset.DAYS, {"weekdays": [MON], "week": NOV(16)}, {}),  # dates come from the occurrence
        (FlexPreset.DAY, {"day": NOV(16)}, {}),
        (FlexPreset.BEFORE_DEADLINE, {}, {}),
    ],
)
def test_bad_templates_rejected(preset: FlexPreset, params: dict[str, Any], fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ItemTemplate(preset, params, **fields)


def test_weekly_rule_needs_weekdays() -> None:
    with pytest.raises(ValueError):
        Rule("weekly")


def test_item_needs_series_id_and_date_together() -> None:
    with pytest.raises(ValueError):
        Item("Lecture", FlexPreset.EXACT, occurrence_date=NOV(17))


# RRULE


def test_rrule_round_trip() -> None:
    text = "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;UNTIL=20261231"
    rule, end = series_rule_from_rrule(text, NOV(16))
    assert (rule, end) == (Rule("weekly", 2, [MON, WED]), date(2026, 12, 31))
    assert rule_to_rrule(rule, end) == text


def test_rrule_count_becomes_end_date() -> None:
    rule, end = series_rule_from_rrule("RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4", NOV(17))
    assert end == NOV(26)  # Tue 17, Thu 19, Tue 24, Thu 26


def test_rrule_weekly_without_byday_uses_start_weekday() -> None:
    rule, _ = series_rule_from_rrule("FREQ=WEEKLY", NOV(18))
    assert rule.weekdays == [WED]


@pytest.mark.parametrize(
    "text",
    [
        "FREQ=MONTHLY",
        "FREQ=WEEKLY;BYMONTHDAY=1",
        "FREQ=WEEKLY;BYDAY=1MO",
        "FREQ=WEEKLY;BYDAY=MO;COUNT=3;UNTIL=20261231",
        "FREQ=WEEKLY;BYDAY=MO;WKST=SU",
    ],
)
def test_unsupported_rrules_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        series_rule_from_rrule(text, NOV(16))
