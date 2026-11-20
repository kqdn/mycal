"""Turn a Series into occurrence Items for the week being planned. Not part of the solver.

Occurrences are created before preset compilation. Template values are copied
once, when an occurrence is created, so editing a series only reaches future
occurrences; an existing occurrence is edited directly.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mycal.model import FlexPreset, Item, Rule, Series

RRULE_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
RRULE_PARTS = {"FREQ", "INTERVAL", "BYDAY", "UNTIL", "COUNT", "WKST"}


def occurrence_dates(series: Series, first: date, last: date) -> list[date]:
    """The series' local dates in [first, last], inside its bounds and not skipped."""
    end = min(last, series.end_date) if series.end_date else last
    skipped = set(series.skipped_dates)
    day = max(first, series.start_date)
    dates = []
    while day <= end:
        if day not in skipped and _matches(series.rule, series.start_date, day):
            dates.append(day)
        day += timedelta(days=1)
    return dates


def _matches(rule: Rule, start: date, day: date) -> bool:
    """Does `day` match the rule, counting intervals from `start`?

    Weekly intervals count Monday-starting weeks, iCalendar's default.
    """
    if rule.freq == "daily":
        return (day - start).days % rule.interval == 0
    weeks = (_monday(day) - _monday(start)).days // 7
    return day.weekday() in rule.weekdays and weeks % rule.interval == 0


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def expand_series(series: Series, existing: list[Item], first: date, last: date) -> list[Item]:
    """New occurrence Items for [first, last].

    Dates that already have an item with this series_id are skipped, so
    running it twice creates nothing new.
    """
    taken = {item.occurrence_date for item in existing if item.series_id == series.id}
    return [_occurrence(series, day) for day in occurrence_dates(series, first, last) if day not in taken]


def occurrence_on(series: Series, day: date) -> Item:
    """The occurrence Item for one date, whether or not the rule falls on it. For a caller
    linking an existing item to a new series on that item's own date."""
    return _occurrence(series, day)


def _occurrence(series: Series, day: date) -> Item:
    """Copy the template onto one date, filling dates into the preset params."""
    template = series.template
    zone = ZoneInfo(series.timezone)
    params = dict(template.preset_params)

    def at(on: date, clock: time) -> datetime:
        return datetime.combine(on, clock, tzinfo=zone).astimezone(UTC)

    if template.flex_preset is FlexPreset.EXACT:
        start_time, end_time = params.pop("start_time"), params.pop("end_time")
        end_day = day + timedelta(days=1) if end_time < start_time else day
        params = {"start": at(day, start_time), "end": at(end_day, end_time)}
    elif template.flex_preset in (FlexPreset.DAY, FlexPreset.DAY_RANGE):
        params["day"] = day
    elif template.flex_preset is FlexPreset.DAYS:
        params["week"] = _monday(day)  # the occurrence's week

    return Item(
        title=series.title,
        flex_preset=template.flex_preset,
        preset_params=params,
        checkable=template.checkable,
        estimate_min=template.estimate_min,
        deadline=at(day, template.deadline_time) if template.deadline_time else None,
        max_chunk_min=template.max_chunk_min,
        one_block_per_day=template.one_block_per_day,
        keep_length=template.keep_length,
        on_miss=template.on_miss,
        series_id=series.id,
        occurrence_date=day,
    )


def skip_occurrence(series: Series, day: date) -> Series:
    """The series with `day` added to skipped_dates. The caller deletes that occurrence's item."""
    return replace(series, skipped_dates=sorted(set(series.skipped_dates) | {day}))


def rule_to_rrule(rule: Rule, end_date: date | None = None) -> str:
    """Format a rule (and optional end date) as an iCalendar RRULE value."""
    parts = [f"FREQ={rule.freq.upper()}"]
    if rule.interval != 1:
        parts.append(f"INTERVAL={rule.interval}")
    if rule.weekdays:
        parts.append("BYDAY=" + ",".join(RRULE_DAYS[d] for d in sorted(rule.weekdays)))
    if end_date is not None:
        parts.append(f"UNTIL={end_date:%Y%m%d}")
    return ";".join(parts)


def series_rule_from_rrule(text: str, start_date: date) -> tuple[Rule, date | None]:
    """Parse an RRULE value into a Rule and an end date.

    COUNT is converted to the date of the last occurrence, which is exact:
    iCalendar counts before removing excluded dates, and so does a fixed end
    date. UNTIL keeps only its date part. Anything outside the subset raises
    ValueError naming the part.
    """
    parts: dict[str, str] = {}
    for part in text.removeprefix("RRULE:").split(";"):
        if part:
            key, _, value = part.partition("=")
            parts[key.upper()] = value.upper()

    if unknown := set(parts) - RRULE_PARTS:
        raise ValueError(f"RRULE parts not supported: {sorted(unknown)}")
    if parts.get("WKST", "MO") != "MO":
        raise ValueError("RRULE WKST other than MO is not supported")
    if "COUNT" in parts and "UNTIL" in parts:
        raise ValueError("RRULE cannot have both COUNT and UNTIL")

    freq = parts.get("FREQ", "").lower()
    if freq not in ("daily", "weekly"):
        raise ValueError(f"RRULE FREQ={parts.get('FREQ')} is not supported")

    weekdays: list[int] = []
    if "BYDAY" in parts:
        for code in parts["BYDAY"].split(","):
            if code not in RRULE_DAYS:
                raise ValueError(f"RRULE BYDAY value {code!r} is not supported")
            weekdays.append(RRULE_DAYS.index(code))
    elif freq == "weekly":
        weekdays = [start_date.weekday()]  # iCalendar default: the start date's weekday

    rule = Rule(freq, int(parts.get("INTERVAL", "1")), sorted(weekdays))  # type: ignore[arg-type]

    end_date = None
    if "UNTIL" in parts:
        end_date = datetime.strptime(parts["UNTIL"][:8], "%Y%m%d").date()
    elif "COUNT" in parts:
        end_date = _nth_occurrence(rule, start_date, int(parts["COUNT"]))
    return rule, end_date


def _nth_occurrence(rule: Rule, start: date, count: int) -> date:
    if count < 1:
        raise ValueError("RRULE COUNT must be at least 1")
    day, seen = start, 0
    while True:
        if _matches(rule, start, day):
            seen += 1
            if seen == count:
                return day
        day += timedelta(days=1)
