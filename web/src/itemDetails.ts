// The item details popover as pure logic: its text lines, where it goes on
// screen, and which week to show after a delete. ItemPopover.tsx only renders
// this. See web/DESIGN.md, "Item details popover".

import type { Block, Week } from './api'
import { dayName, estimateLabel, range12, toLocal, type DateString } from './time'

export interface UnscheduledItem {
  title: string
  estimate_min: number | null
  reason: string | null
  sessions: number
  editable: boolean
  series_id?: string | null // set on an occurrence of a stored series
}

/** "Tue, Nov 17, 2:00 to 2:30pm", or "... (ends the next day)" for a block that runs past midnight. */
export function whenLine(block: Pick<Block, 'start' | 'end'>, timezone: string): string {
  const start = toLocal(block.start, timezone)
  const end = toLocal(block.end, timezone)
  const nextDay = end.date > start.date && end.minutes > 0
  return `${dayName(start.date)}, ${range12(start.minutes, end.minutes)}${nextDay ? ' (ends the next day)' : ''}`
}

/**
 * "Placed by the solver · Session 2 of 4 · 2h in all". The session part shows
 * when there is more than one session. "2h of 4h placed" replaces "2h in all"
 * when work is still waiting, and shows even for a single session, since it
 * says the item isn't all planned. "Already started" when the block began
 * before `now` (a UTC ISO time).
 */
export function kindLine(block: Block, now: string): string {
  const parts = [block.fixed ? 'Fixed' : 'Placed by the solver']
  const waiting = block.estimate_min !== null && block.placed_min < block.estimate_min
  if (block.sessions > 1) parts.push(`Session ${block.session} of ${block.sessions}`)
  if (waiting) parts.push(`${estimateLabel(block.placed_min)} of ${estimateLabel(block.estimate_min!)} placed`)
  else if (block.sessions > 1) parts.push(`${estimateLabel(block.placed_min)} in all`)
  if (Date.parse(block.start) <= Date.parse(now)) parts.push('Already started')
  return parts.join(' · ')
}

/** The kind line for an Unscheduled row: its reason, or why it has no times, then its estimate. */
export function unscheduledLine(item: UnscheduledItem): string {
  const why = item.reason ?? 'Not scheduled: it has no times to go in yet'
  return item.estimate_min === null ? why : `${why} · ${estimateLabel(item.estimate_min)}`
}

/** What a delete takes with it. */
export function confirmLine(sessions: number): string {
  if (sessions === 0) return 'It has no sessions yet.'
  if (sessions === 1) return 'Its one session goes.'
  return `All ${sessions} sessions go, in every week.`
}

export interface Rect {
  left: number
  top: number
  right: number
  bottom: number
}

export interface Size {
  width: number
  height: number
}

const GAP = 8 // from what opened it
const MARGIN = 16 // from the window's edges

/**
 * Where the popover goes, in window coordinates. Next to a block (right if
 * there is room, else left, top-aligned), or under a row's button (right-
 * aligned). Always kept MARGIN inside the window.
 */
export function popoverPosition(anchor: Rect, size: Size, viewport: Size, place: 'beside' | 'below'): { left: number; top: number } {
  let left: number
  let top: number
  if (place === 'beside') {
    left = anchor.right + GAP
    if (left + size.width > viewport.width - MARGIN) left = anchor.left - GAP - size.width
    top = anchor.top
  } else {
    left = anchor.right - size.width
    top = anchor.bottom + GAP
    if (top + size.height > viewport.height - MARGIN) top = anchor.top - GAP - size.height
  }
  return {
    left: clamp(left, MARGIN, viewport.width - MARGIN - size.width),
    top: clamp(top, MARGIN, viewport.height - MARGIN - size.height),
  }
}

/** Keep `value` in [low, high]; when the box is bigger than the room, stick to `low`. */
function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(value, high))
}

/** After a delete: show the returned week only if it's still the one being viewed. */
export function weekAfterDelete(viewing: DateString, returned: Week): Week | null {
  return returned.week_start === viewing ? returned : null
}
