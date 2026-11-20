// Turns UTC spans into pieces of the week grid: which day column, and which
// minutes of that local day. A span that crosses local midnight becomes one
// piece per day, so Fri 5pm to Sat 2am shows in both columns.

import type { Week } from './api'
import { addDays, toLocal, type DateString } from './time'

export interface Span {
  start: string // UTC ISO
  end: string
}

export interface Piece {
  day: number // column, 0 = the week's Monday
  startMin: number // minutes since local midnight
  endMin: number // up to 1440
  continuesBefore: boolean // the span started on an earlier day
  continuesAfter: boolean // the span goes on into a later day
}

const DAY_MIN = 24 * 60

/** The 7 dates of the week starting `weekStart`. */
export function weekDates(weekStart: DateString): DateString[] {
  return Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))
}

/** Split a span at local midnights and keep the pieces that fall inside the week. */
export function pieces(span: Span, weekStart: DateString, timeZone: string): Piece[] {
  const start = toLocal(span.start, timeZone)
  const end = toLocal(span.end, timeZone)
  const dates = weekDates(weekStart)
  const result: Piece[] = []

  for (let date = start.date; date <= end.date; date = addDays(date, 1)) {
    const first = date === start.date
    const last = date === end.date
    const startMin = first ? start.minutes : 0
    const endMin = last ? end.minutes : DAY_MIN
    const day = dates.indexOf(date)
    if (endMin <= startMin || day === -1) continue // ends exactly at midnight, or outside the week
    // Ending at exactly midnight leaves no piece on the next day.
    const continuesAfter = !last && !(addDays(date, 1) === end.date && end.minutes === 0)
    result.push({ day, startMin, endMin, continuesBefore: !first, continuesAfter })
  }
  return result
}

/** Where to scroll to show some blocks, like the ones a proposal changes: the earliest start minus 30 minutes, or null with none in the week. */
export function scrollMinuteFor(spans: Span[], weekStart: DateString, timeZone: string): number | null {
  const first = earliestStart(spans, weekStart, timeZone)
  return first === null ? null : Math.max(0, first - 30)
}

/** The earliest local minute any span starts on any of the 7 days, ignoring tails of the night before. */
function earliestStart(spans: Span[], weekStart: DateString, timeZone: string): number | null {
  const starts = spans
    .flatMap((span) => pieces(span, weekStart, timeZone))
    .filter((p) => !p.continuesBefore)
    .map((p) => p.startMin)
  return starts.length ? Math.min(...starts) : null
}

/**
 * The minute of the day to scroll to on load (web/DESIGN.md, Initial scroll):
 * the earliest block start on any day, weekends included, minus 30 minutes.
 * With no blocks, the earliest work-frame start instead; with neither, the top.
 */
export function initialScrollMinute(week: Week): number {
  const { week_start: weekStart, timezone } = week
  const first = earliestStart(week.blocks, weekStart, timezone) ?? earliestStart(week.frames, weekStart, timezone)
  return first === null ? 0 : Math.max(0, first - 30)
}

// Pixel sizes. HOUR_HEIGHT mirrors --hour-height in tokens.css: JS needs the
// number to place blocks, so keep the two in step (see web/DESIGN.md).
export const HOUR_HEIGHT = 52

export function minutesToPx(minutes: number): number {
  return (minutes * HOUR_HEIGHT) / 60
}

/** The start of the slot under a point `offsetPx` below a day column's top, in minutes after midnight. */
export function slotAt(offsetPx: number, slotMin: number): number {
  const minutes = (offsetPx * 60) / HOUR_HEIGHT
  const slot = Math.floor(minutes / slotMin) * slotMin
  return Math.min(Math.max(slot, 0), 24 * 60 - slotMin)
}

/** Whether a slot starting at a local date and minute has already begun, so nothing can be added there. */
export function slotHasBegun(date: DateString, minutes: number, now: { date: DateString; minutes: number }): boolean {
  return date < now.date || (date === now.date && minutes < now.minutes)
}

export type TextMode = 'two-line' | 'one-line' | 'title-only'

/**
 * What a block shows at its height (web/DESIGN.md, Text by height). With
 * 15-minute slots: 1 hour and longer gets two lines, 30 and 45 min one line,
 * 15 min the title only.
 */
export function textMode(heightPx: number): TextMode {
  if (heightPx >= 40) return 'two-line'
  if (heightPx >= 20) return 'one-line'
  return 'title-only'
}
