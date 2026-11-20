// Dragging a block to move it (Milestone 9, web/DESIGN.md "Dragging a block"). The rules here
// match the server's (POST /api/blocks/{id}/move), so a refused spot shows before the drop.

import type { Block } from './api'
import type { ItemForm } from './itemForm'
import { weekdayOf } from './repeatForm'
import { fromLocal, type DateString, type LocalMoment } from './time'

/**
 * Whether a block can be dragged: a session or fixed event that isn't answered yet, as for "+15 min":
 * before it starts, while it runs, or (with check-ins) until it's checked in. Not a kept record. A fixed
 * event also has to be one the edit dialog can change (not Custom), since moving it edits it.
 */
export function canDrag(block: Block, now: string): boolean {
  const movable = !block.fixed || block.editable
  const open = block.checkable || Date.parse(now) < Date.parse(block.end)
  return movable && !block.deleted && block.status === 'planned' && open
}

/** Where a dragged block would land, and why it can't go there (null when it can). */
export interface Drop {
  start: string // UTC ISO
  end: string
  problem: string | null // "Linear algebra is there", "Already past"
  late: boolean // it would end after the item is due: allowed (say, an extension), but warned about
}

/**
 * The spot for `block` with its top at `minutes` on local `date`, keeping its length. Refused over
 * the past and over anything the planner keeps where it is: a fixed event, a finished or locked
 * session, or one that started. Sessions the planner placed don't refuse it, since they move.
 */
export function dropAt(block: Block, date: DateString, minutes: number, blocks: Block[], timezone: string, now: string): Drop {
  const start = fromLocal(date, minutes, timezone)
  const end = new Date(Date.parse(start) + Date.parse(block.end) - Date.parse(block.start)).toISOString()
  const late = afterDue(end, block.due)
  // It only has to end after now: a running session may move to when it really started.
  if (Date.parse(end) <= Date.parse(now)) return { start, end, problem: 'Already past', late }
  // A fixed event may overlap anything (double booking, marked in the new plan); sessions move around it.
  if (block.fixed) return { start, end, problem: null, late }
  const blocker = blocks.find(
    (other) =>
      other.id !== block.id &&
      Date.parse(other.start) < Date.parse(end) &&
      Date.parse(other.end) > Date.parse(start) &&
      (other.fixed || other.locked || other.status !== 'planned' || Date.parse(other.start) <= Date.parse(now)),
  )
  return { start, end, problem: blocker ? `${blocker.title} is there` : null, late }
}

/** "09:05" for 545 minutes; an end at midnight the next day is "00:00", which the server reads as overnight. */
function clock(minutes: number): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`
}

/** A fixed event's edit form moved to a new local start and end ("This event only", or a one-off event). */
export function movedEvent(form: ItemForm, start: LocalMoment, end: LocalMoment): ItemForm {
  return { ...form, day: start.date, startTime: clock(start.minutes), endTime: clock(end.minutes) }
}

/**
 * A repeating event's form moved for "All events": its new times, and for a weekly series moved to
 * another day, that weekday in place of the old one (`from`, the dragged occurrence's date).
 */
export function movedSeries(form: ItemForm, from: DateString, start: LocalMoment, end: LocalMoment): ItemForm {
  const times = { startTime: clock(start.minutes), endTime: clock(end.minutes) }
  const [old, now] = [weekdayOf(from), weekdayOf(start.date)]
  if (form.repeat !== 'weekly' || old === now) return { ...form, ...times }
  const days = new Set(form.repeatDays.filter((d) => d !== old))
  days.add(now)
  return { ...form, ...times, repeatDays: [...days].sort((a, b) => a - b) }
}

/** Whether a session ending at `end` runs past its item's deadline (`due`, for a "before a deadline" item). */
export function afterDue(end: string, due: string | null | undefined): boolean {
  return !!due && Date.parse(end) > Date.parse(due)
}
