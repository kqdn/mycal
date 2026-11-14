"""Milestone 1 demo: load a TOML week file, solve it and print the schedule.

Not part of the solver: this module does the file I/O and printing.
Local dates, times and datetimes in the file are in the file's `timezone`;
see examples/week.toml for the format.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from mycal.model import Constraint, FlexPreset, Item, ItemTemplate, OnMiss, Series, Window, WorkFrame
from mycal.presets import compile_windows
from mycal.recurrence import expand_series, series_rule_from_rrule
from mycal.settings import SolverSettings
from mycal.solve import SolveResult, solve

ITEM_FIELDS = {
    "title", "preset", "estimate_min", "max_chunk_min", "deadline", "checkable",
    "on_miss", "one_block_per_day", "depends_on",
}
SERIES_FIELDS = {
    "title", "rrule", "start_date", "end_date", "skipped_dates", "preset", "estimate_min",
    "deadline_time", "checkable", "on_miss", "max_chunk_min", "one_block_per_day",
}
PARAM_KEYS = {
    FlexPreset.EXACT: {"start", "end"},
    FlexPreset.DAY: {"day"},
    FlexPreset.DAY_RANGE: {"day", "start_time", "end_time"},
    FlexPreset.DAYS: {"weekdays", "start_time", "end_time"},
    FlexPreset.BEFORE_DEADLINE: set(),
    FlexPreset.CUSTOM: {"windows"},
}


@dataclass(slots=True)
class Week:
    settings: SolverSettings
    start: date
    work_frames: list[WorkFrame]
    items: list[Item]
    series: list[Series] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)

    def horizon(self) -> tuple[datetime, datetime]:
        """Monday 00:00 local to the next Monday 00:00 local, in UTC."""
        zone = ZoneInfo(self.settings.timezone)
        start = datetime.combine(self.start, time(), tzinfo=zone)
        end = datetime.combine(self.start + timedelta(days=7), time(), tzinfo=zone)
        return start.astimezone(UTC), end.astimezone(UTC)


def load_week(path: Path) -> Week:
    return parse_week(tomllib.loads(path.read_text(encoding="utf-8")))


def parse_week(data: dict[str, Any]) -> Week:
    """Build settings, work frames and items from a parsed TOML week."""
    timezone = data["timezone"]
    settings = SolverSettings(timezone, slot_min=data.get("slot_min", 15))
    zone = ZoneInfo(timezone)

    frames = [
        WorkFrame(f["name"], f["weekdays"], f["start_time"], f["end_time"], timezone)
        for f in data.get("work_frames", [])
    ]

    raw_items = data.get("items", [])
    ids: dict[str, UUID] = {}
    for raw in raw_items:
        title = raw["title"]
        if title in ids:
            raise ValueError(f"Duplicate item title {title!r}; titles must be unique")
        ids[title] = uuid4()

    items = []
    for raw in raw_items:
        try:
            items.append(_parse_item(raw, ids, zone))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Item {raw['title']!r}: {error}") from error

    series = []
    for raw in data.get("series", []):
        try:
            series.append(_parse_series(raw, timezone))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Series {raw.get('title')!r}: {error}") from error

    constraints = [
        Constraint(
            kind=raw["kind"],
            params={key: value for key, value in raw.items() if key not in ("kind", "hard", "weight")},
            weight=raw.get("weight", 1.0),
            hard=raw.get("hard", False),
        )
        for raw in data.get("constraints", [])
    ]

    return Week(settings, data["week_start"], frames, items, series, constraints)


def _parse_series(raw: dict[str, Any], timezone: str) -> Series:
    """A [[series]] table: an RRULE plus template fields; other keys are template params."""
    start_date = raw["start_date"]
    rule, rrule_end = series_rule_from_rrule(raw["rrule"], start_date)
    if rrule_end is not None and "end_date" in raw:
        raise ValueError("give the end in rrule (UNTIL or COUNT) or end_date, not both")
    template = ItemTemplate(
        flex_preset=FlexPreset(raw["preset"]),
        preset_params={key: value for key, value in raw.items() if key not in SERIES_FIELDS},
        estimate_min=raw.get("estimate_min"),
        deadline_time=raw.get("deadline_time"),
        checkable=raw.get("checkable", False),
        on_miss=OnMiss(raw.get("on_miss", "reschedule")),
        max_chunk_min=raw.get("max_chunk_min"),
        one_block_per_day=raw.get("one_block_per_day", False),
    )
    return Series(
        title=raw["title"],
        rule=rule,
        timezone=timezone,
        start_date=start_date,
        template=template,
        end_date=raw.get("end_date", rrule_end),
        skipped_dates=raw.get("skipped_dates", []),
    )


def _parse_item(raw: dict[str, Any], ids: dict[str, UUID], zone: ZoneInfo) -> Item:
    preset = FlexPreset(raw["preset"])
    params = {key: value for key, value in raw.items() if key not in ITEM_FIELDS}
    unknown = set(params) - PARAM_KEYS[preset]
    if unknown:
        raise ValueError(f"unknown keys for preset {preset.value!r}: {sorted(unknown)}")

    for key in ("start", "end"):
        if key in params:
            params[key] = _to_utc(params[key], zone)
    if "windows" in params:
        params["windows"] = [
            Window(_to_utc(w["start"], zone), _to_utc(w["end"], zone)) for w in params["windows"]
        ]

    missing = [title for title in raw.get("depends_on", []) if title not in ids]
    if missing:
        raise ValueError(f"depends_on names unknown items {missing}")

    deadline = raw.get("deadline")
    return Item(
        title=raw["title"],
        flex_preset=preset,
        preset_params=params,
        checkable=raw.get("checkable", False),
        estimate_min=raw.get("estimate_min"),
        deadline=_to_utc(deadline, zone) if deadline is not None else None,
        depends_on=[ids[title] for title in raw.get("depends_on", [])],
        max_chunk_min=raw.get("max_chunk_min"),
        one_block_per_day=raw.get("one_block_per_day", False),
        on_miss=OnMiss(raw.get("on_miss", "reschedule")),
        id=ids[raw["title"]],
    )


def _to_utc(value: datetime, zone: ZoneInfo) -> datetime:
    """TOML local datetimes are read as local time in `zone`; offset datetimes keep their offset."""
    if not isinstance(value, datetime):
        raise ValueError(f"expected a datetime, got {value!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    return value.astimezone(UTC)


def plan_week(week: Week) -> tuple[list[Item], SolveResult]:
    """Create this week's series occurrences, compile every item's windows, then solve."""
    start, end = week.horizon()
    timezone = week.settings.timezone
    last_day = week.start + timedelta(days=6)
    occurrences = [
        item for s in week.series for item in expand_series(s, week.items, week.start, last_day)
    ]
    items = [
        replace(item, windows=compile_windows(item, week.work_frames, timezone, start, end))
        for item in week.items + occurrences
    ]
    return items, solve(items, [], week.work_frames, week.constraints, week.settings)


def format_schedule(items: list[Item], result: SolveResult, timezone: str) -> str:
    """The schedule as text: one heading per local day, then unscheduled items."""
    if not result.feasible:
        return "No arrangement fits this week: some deadline, window or dependency can't be met."

    zone = ZoneInfo(timezone)
    titles = {item.id: item.title for item in items}
    lines: list[str] = []
    current_day: date | None = None
    for block in result.blocks:
        start, end = block.start.astimezone(zone), block.end.astimezone(zone)
        if start.date() != current_day:
            current_day = start.date()
            if lines:
                lines.append("")
            lines.append(f"{start:%a %b} {start.day}")
        lines.append(f"  {start:%H:%M}-{end:%H:%M}  {titles[block.item_id]}")

    unscheduled = [item.title for item in items if not item.windows]
    if unscheduled:
        lines += ["", "Unscheduled"] + [f"  {title}" for title in unscheduled]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: mycal-demo WEEK.toml", file=sys.stderr)
        return 2
    try:
        week = load_week(Path(args[0]))
    except (OSError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    items, result = plan_week(week)
    print(format_schedule(items, result, week.settings.timezone))
    return 0 if result.feasible else 1
