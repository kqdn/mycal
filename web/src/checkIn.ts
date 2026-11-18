// Check-ins as pure logic (Milestone 7): the check-in dialog's form, its
// request, and the lines the banner, grid and popover show. CheckInDialog.tsx
// and the others only render this. See web/DESIGN.md, "Check-ins".

import type { Block, CheckIn, CheckInRequest, MissedAction } from './api'
import { estimateLabel } from './time'
import { parseDuration } from './itemForm'

export type Answer = CheckInRequest['answer']

/** What the check-in dialog is about: a pending check-in, or a past block whose answer can change. */
export type CheckInTarget = Pick<CheckIn, 'block_id' | 'title' | 'start' | 'end' | 'status' | 'done_min' | 'on_miss' | 'choices'>

export const ANSWERS: { value: Answer; label: string }[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'partly', label: 'Partly' },
  { value: 'no', label: 'No' },
]

export const ACTION_LABELS: Record<MissedAction, string> = {
  reschedule: 'Reschedule',
  catch_up: 'Catch up',
  skip: 'Skip',
}

/** The check-in dialog's fields, as chosen and typed. */
export interface CheckInForm {
  answer: Answer | null
  done: string // how much got done, for Partly: "30m", "1h 15m"
  action: MissedAction | null // what happens to the missed time
}

export type CheckInErrors = Partial<Record<'answer' | 'done' | 'action', string>>

/** The check-in target for a block in the grid (its popover's Check in or Change answer). */
export function targetFromBlock(block: Block): CheckInTarget {
  return {
    block_id: block.id,
    title: block.title,
    start: block.start,
    end: block.end,
    status: block.status,
    done_min: block.done_min,
    on_miss: block.on_miss,
    choices: block.fixed ? ['catch_up', 'skip'] : ['reschedule', 'catch_up', 'skip'],
  }
}

/** A fresh form: the earlier answer, if any, and the item's own policy for the missed time. */
export function emptyCheckIn(target: CheckInTarget): CheckInForm {
  const answers: Partial<Record<CheckInTarget['status'], Answer>> = { done: 'yes', partial: 'partly', missed: 'no' }
  const policy = target.on_miss === 'ask' ? null : target.on_miss
  return {
    answer: answers[target.status] ?? null,
    done: target.status === 'partial' && target.done_min !== null ? estimateLabel(target.done_min) : '',
    action: policy !== null && target.choices.includes(policy) ? policy : null,
  }
}

export function lengthMin(target: Pick<CheckInTarget, 'start' | 'end'>): number {
  return Math.round((Date.parse(target.end) - Date.parse(target.start)) / 60_000)
}

/** Whether the form asks what happens to the missed time: for Partly and No. */
export const asksAction = (form: CheckInForm) => form.answer === 'partly' || form.answer === 'no'

export function validateCheckIn(form: CheckInForm, target: CheckInTarget): CheckInErrors {
  const errors: CheckInErrors = {}
  if (form.answer === null) errors.answer = 'Pick Yes, Partly or No.'
  if (form.answer === 'partly') {
    const done = parseDuration(form.done)
    const length = lengthMin(target)
    if (done === null || done >= length) {
      errors.done = `Use a length shorter than the session's ${estimateLabel(length)}, like 30m.`
    }
  }
  if (asksAction(form) && form.action === null) errors.action = 'Pick what happens to the time you missed.'
  return errors
}

/** The request for a valid form. The action is always sent for Partly and No, so the choice shown is the one that runs. */
export function checkInRequest(form: CheckInForm, acceptShortfall = false): CheckInRequest {
  const request: CheckInRequest = { answer: form.answer ?? 'yes' }
  if (form.answer === 'partly') request.done_min = parseDuration(form.done) ?? undefined
  if (asksAction(form) && form.action !== null) request.action = form.action
  if (acceptShortfall) request.accept_shortfall = true
  return request
}

/** The banner's title: "1 session to check in", "3 sessions to check in". */
export function bannerTitle(count: number): string {
  return `${count} ${count === 1 ? 'session' : 'sessions'} to check in`
}

/** How a block looks in the grid: done (done or partly done), missed (missed or no answer), else fixed or placed. */
export function blockKind(block: Pick<Block, 'fixed' | 'status'>): 'done' | 'missed' | 'fixed' | 'placed' {
  if (block.status === 'done' || block.status === 'partial') return 'done'
  if (block.status === 'missed' || block.status === 'unanswered') return 'missed'
  return block.fixed ? 'fixed' : 'placed'
}

/** Whether a block is waiting for its check-in: checkable, ended, and not answered. `now` is UTC ISO. */
export function awaitsCheckIn(block: Pick<Block, 'checkable' | 'status' | 'end'>, now: string): boolean {
  return block.checkable && block.status === 'planned' && Date.parse(block.end) <= Date.parse(now)
}

/** Whether the popover offers a check-in: a checkable block that has started. */
export function canCheckIn(block: Pick<Block, 'checkable' | 'start'>, now: string): boolean {
  return block.checkable && Date.parse(block.start) <= Date.parse(now)
}

const WHAT_RAN: Record<MissedAction, string> = {
  reschedule: 'rescheduled',
  catch_up: 'caught up later',
  skip: 'skipped',
}

/**
 * The popover's check-in line, or '' when there is nothing to say: "Done",
 * "Partly done: 30m of 1h · The rest is rescheduled", "Missed · Caught up later",
 * "No answer · Rescheduled", "Waiting for a check-in", "Missed · Waiting for your choice".
 */
export function checkInLine(block: Block, now: string): string {
  const missed = (what: string) =>
    block.missed_action === null ? `${what} · Waiting for your choice` : `${what} · ${capital(WHAT_RAN[block.missed_action])}`
  switch (block.status) {
    case 'done':
      return 'Done'
    case 'partial': {
      const done = `Partly done: ${estimateLabel(block.done_min ?? 0)} of ${estimateLabel(lengthMin(block))}`
      return block.missed_action === null
        ? `${done} · The rest waits for your choice`
        : `${done} · The rest is ${WHAT_RAN[block.missed_action]}`
    }
    case 'missed':
      return missed('Missed')
    case 'unanswered':
      return missed('No answer')
    case 'planned':
      return awaitsCheckIn(block, now) ? 'Waiting for a check-in' : ''
  }
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** A check-in's pending list as a stable key, to notice when the server changed it (say, one went unanswered). */
export function pendingKey(checkIns: Pick<CheckIn, 'block_id' | 'status'>[]): string {
  return checkIns.map((c) => `${c.block_id}:${c.status}`).join(',')
}
