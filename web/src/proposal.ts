// The compare view (Milestone 8, web/DESIGN.md "Compare view"): what a waiting proposal changes in the week.

import type { Block, CheckInRequest, Proposal, Week } from './api'
import { whenLine } from './itemDetails'
import type { OnMiss } from './itemForm'
import { estimateLabel, time12, toLocal, weekdayShort } from './time'

export type ChangeKind = 'new' | 'moved' | 'resized' | 'removed'

/** One row of the changes list: a block that is new, moves, changes length or leaves the week. */
export interface Change {
  blockId: string
  title: string
  kind: ChangeKind
  text: string // "Moves from Thu 6:00pm to Fri 4:30pm"
}

/**
 * The blocks of the week that differ between the current plan and the proposal, matched by id
 * (a re-plan keeps a block's id when the block stays). In the order they come in the week,
 * a removed block by where it was.
 */
export function proposalChanges(current: Block[], proposed: Block[], timezone: string): Change[] {
  const before = new Map(current.map((b) => [b.id, b]))
  const after = new Map(proposed.map((b) => [b.id, b]))
  const rows: { at: string; change: Change }[] = []
  for (const block of proposed) {
    const old = before.get(block.id)
    const change = old ? changeOf(old, block, timezone) : newBlock(block, timezone)
    if (change) rows.push({ at: block.start, change })
  }
  for (const old of current) {
    if (!after.has(old.id)) {
      rows.push({
        at: old.start,
        change: { blockId: old.id, title: old.title, kind: 'removed', text: `Off this week · was ${whenLine(old, timezone)}` },
      })
    }
  }
  return rows.sort((a, b) => Date.parse(a.at) - Date.parse(b.at)).map((row) => row.change)
}

function newBlock(block: Block, timezone: string): Change {
  return { blockId: block.id, title: block.title, kind: 'new', text: `New · ${whenLine(block, timezone)}` }
}

function changeOf(old: Block, block: Block, timezone: string): Change | null {
  const moved = old.start !== block.start
  const resized = length(old) !== length(block)
  if (!moved && !resized) return null
  const sizes = `${estimateLabel(length(old))} becomes ${estimateLabel(length(block))}`
  if (!moved) return { blockId: block.id, title: block.title, kind: 'resized', text: sizes }
  const text = `Moves from ${moment(old.start, timezone)} to ${moment(block.start, timezone)}`
  return { blockId: block.id, title: block.title, kind: 'moved', text: resized ? `${text} · ${sizes}` : text }
}

/** "Thu 6:00pm" */
export function moment(iso: string, timezone: string): string {
  const local = toLocal(iso, timezone)
  return `${weekdayShort(local.date)} ${time12(local.minutes)}`
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

/** "Essay and Lecture overlap" for each overlapping pair in the proposal. Titles of blocks it can't find are left out. */
export function overlapLines(proposal: Proposal): string[] {
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
