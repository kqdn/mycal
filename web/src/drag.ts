// Dragging a block to move it (Milestone 9, web/DESIGN.md "Dragging a block"). The rules here
// match the server's (POST /api/blocks/{id}/move), so a refused spot shows before the drop.

import type { Block } from './api'
import { fromLocal, type DateString } from './time'

/** Whether a block can be dragged: a work session the planner placed (or you moved) that hasn't started. */
export function canDrag(block: Block, now: string): boolean {
  return !block.fixed && !block.deleted && block.status === 'planned' && Date.parse(block.start) > Date.parse(now)
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
  if (Date.parse(start) < Date.parse(now)) return { start, end, problem: 'Already past', late }
  const blocker = blocks.find(
    (other) =>
      other.id !== block.id &&
      Date.parse(other.start) < Date.parse(end) &&
      Date.parse(other.end) > Date.parse(start) &&
      (other.fixed || other.locked || other.status !== 'planned' || Date.parse(other.start) <= Date.parse(now)),
  )
  return { start, end, problem: blocker ? `${blocker.title} is there` : null, late }
}

/** Whether a session ending at `end` runs past its item's deadline (`due`, for a "before a deadline" item). */
export function afterDue(end: string, due: string | null | undefined): boolean {
  return !!due && Date.parse(end) > Date.parse(due)
}
