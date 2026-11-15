// Turns UTC spans into pieces of the week grid: which day column, and which
// minutes of that local day. A span that crosses local midnight becomes one
// piece per day, so Fri 5pm to Sat 2am shows in both columns.

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

/**
 * The earliest local minute any span starts on any day, for the initial scroll.
 * Pieces that continue from the day before (the tail of a night) don't count.
 */
export function earliestMinute(spans: Span[], weekStart: DateString, timeZone: string): number | null {
  const starts = spans
    .flatMap((span) => pieces(span, weekStart, timeZone))
    .filter((p) => !p.continuesBefore)
    .map((p) => p.startMin)
  return starts.length ? Math.min(...starts) : null
}
