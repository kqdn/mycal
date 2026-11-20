// The compare view (Milestone 8, web/DESIGN.md "Compare view"): what a waiting proposal changes in the week.

import type { Block, CheckInRequest, Proposal, Week } from './api'
import { afterDue } from './drag'
import { whenLine } from './itemDetails'
import type { OnMiss } from './itemForm'
import { estimateLabel, time12, toLocal, weekdayShort, weekTitle, type DateString } from './time'

export type ChangeKind = 'new' | 'moved' | 'resized' | 'removed'
export type Arrow = 'up' | 'down' | 'left' | 'right'
type Span = Pick<Block, 'start' | 'end'>

/** One change in the week: a block that is new, moves, changes length or leaves the week. */
export interface Change {
  blockId: string
  title: string
  kind: ChangeKind
  text: string // the changes list: "Moves from Thu 6:00pm to Fri 4:30pm"
  before: Span | null // where it is in the current plan
  after: Span | null // where the proposal puts it
  // Its tag in the grid, in the proposal and in the current plan, with an arrow for a move.
  tagProposal: string | null // "From 6:00pm", "New", "Was 2h"
  tagCurrent: string | null // "To 4:30pm", "Off this week", "Becomes 1h 30m"
  arrow: Arrow | null // up or down within a day, left or right to another day
}

/**
 * The blocks of the week that differ between the current plan and the proposal, matched by
 * block id: a re-plan keeps a block's id while it stays, and an item can have several blocks,
 * so matching by item would mix up its sessions. In the order they come in the week, a removed
 * block by where it was.
 */
export function proposalChanges(current: Block[], proposed: Block[], timezone: string): Change[] {
  const before = new Map(current.map((b) => [b.id, b]))
  const after = new Map(proposed.map((b) => [b.id, b]))
  const rows: { at: string; change: Change }[] = []
  for (const block of proposed) {
    const old = before.get(block.id)
    const change = old ? changeOf(old, block, timezone) : newBlock(block, timezone)
    // A spot after the deadline is allowed (you may have dragged it there), but the tile says so.
    if (change && afterDue(block.end, block.due)) change.text += " · After it's due"
    if (change) rows.push({ at: block.start, change })
  }
  for (const old of current) {
    if (!after.has(old.id)) rows.push({ at: old.start, change: removedBlock(old, timezone) })
  }
  return rows.sort((a, b) => Date.parse(a.at) - Date.parse(b.at)).map((row) => row.change)
}

function newBlock(block: Block, timezone: string): Change {
  return {
    blockId: block.id, title: block.title, kind: 'new', text: `New · ${whenLine(block, timezone)}`,
    before: null, after: block, tagProposal: 'New', tagCurrent: null, arrow: null,
  }
}

function removedBlock(old: Block, timezone: string): Change {
  return {
    blockId: old.id, title: old.title, kind: 'removed', text: `Off this week · was ${whenLine(old, timezone)}`,
    before: old, after: null, tagProposal: null, tagCurrent: 'Off this week', arrow: null,
  }
}

function changeOf(old: Block, block: Block, timezone: string): Change | null {
  const moved = old.start !== block.start
  const resized = length(old) !== length(block)
  if (!moved && !resized) return null
  const sizes = `${estimateLabel(length(old))} becomes ${estimateLabel(length(block))}`
  const common = { blockId: block.id, title: block.title, before: old, after: block }
  if (!moved) {
    return {
      ...common, kind: 'resized', text: sizes, arrow: null,
      tagProposal: `Was ${estimateLabel(length(old))}`, tagCurrent: `Becomes ${estimateLabel(length(block))}`,
    }
  }
  const from = toLocal(old.start, timezone)
  const to = toLocal(block.start, timezone)
  const sameDay = from.date === to.date
  // The day shows only when it changes: "Moves from Mon 5:00pm to 6:00pm", "From Thu 4:30pm".
  const at = (local: typeof from) => (sameDay ? time12(local.minutes) : `${weekdayShort(local.date)} ${time12(local.minutes)}`)
  const text = `Moves from ${weekdayShort(from.date)} ${time12(from.minutes)} to ${at(to)}`
  return {
    ...common,
    kind: 'moved',
    text: resized ? `${text} · ${sizes}` : text,
    tagProposal: `From ${at(from)}`,
    tagCurrent: `To ${at(to)}`,
    arrow: sameDay ? (to.minutes < from.minutes ? 'up' : 'down') : to.date < from.date ? 'left' : 'right',
  }
}

/**
 * The other spot of a selected change, as a dashed outline: where it was (in the proposal) or where
 * it goes (in the current plan). A block that only changes length says its other length: "Was 7h".
 */
export function otherSpot(change: Change, showProposal: boolean): { span: Span; label: string } | null {
  const span = showProposal ? change.before : change.after
  if (!span) return null
  const length = showProposal ? change.tagProposal : change.tagCurrent
  const label = change.kind === 'resized' && length ? length : showProposal ? 'Was here' : 'Moves here'
  return { span, label }
}

/** "3 changes from your current plan" */
export function changeCount(count: number): string {
  return `${count} ${count === 1 ? 'change' : 'changes'} from your current plan`
}

/** The changes card's title: the count, or which weeks nothing moves in. */
export function changesTitle(count: number, proposal: Proposal): string {
  if (count > 0) return changeCount(count)
  return proposal.other_weeks.length > 0 ? 'No blocks move in this week' : 'No blocks move'
}

/** "Also 2 changes in Nov 23 to 29" */
export function otherWeekLine(changes: number, weekStart: DateString): string {
  return `Also ${changes} ${changes === 1 ? 'change' : 'changes'} in ${weekTitle(weekStart)}`
}

function length(block: Pick<Block, 'start' | 'end'>): number {
  return Math.round((Date.parse(block.end) - Date.parse(block.start)) / 60_000)
}

/** The blocks a proposal changes in the week, in both plans (where they are and where they would go). */
export function changedBlocks(week: Week): Block[] {
  if (!week.proposal) return []
  const ids = new Set(proposalChanges(week.blocks, week.proposal.blocks, week.timezone).map((c) => c.blockId))
  return [...week.blocks, ...week.proposal.blocks].filter((b) => ids.has(b.id))
}

/** The week as the grid draws it: the current plan, or the proposal's version of it. */
export function shownWeek(week: Week, showProposal: boolean): Week {
  if (!showProposal || !week.proposal) return week
  return { ...week, blocks: week.proposal.blocks, unscheduled: week.proposal.unscheduled }
}

/**
 * "Essay and Lecture overlap" for each overlapping pair in a proposal or a week (double booking, or a
 * session given more time that ran into an event). Titles of blocks it can't find are left out.
 */
export function overlapLines(proposal: Pick<Proposal, 'blocks' | 'overlaps'>): string[] {
  const byId = new Map(proposal.blocks.map((b) => [b.id, b]))
  return proposal.overlaps.flatMap(([a, b]) => {
    const first = byId.get(a)
    const second = byId.get(b)
    return first && second ? [`${first.title} and ${second.title} overlap`] : []
  })
}

/**
 * Whether a check-in answer goes through a proposal: only when it moves work, so a Reschedule or a
 * Catch up. Yes and Skip save right away, since nothing else in the plan changes.
 */
export function checkInProposes(request: CheckInRequest, onMiss: OnMiss): boolean {
  if (request.answer === 'yes') return false
  const action = request.action ?? onMiss
  return action === 'reschedule' || action === 'catch_up'
}
