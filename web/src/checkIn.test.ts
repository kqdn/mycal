import { describe, expect, it } from 'vitest'
import type { Block, CheckInPreview } from './api'
import {
  answerQuestion,
  awaitsCheckIn,
  bannerTitle,
  blockKind,
  canCheckIn,
  canExtend,
  checkInLine,
  checkInRequest,
  emptyCheckIn,
  extendLabel,
  graceLine,
  missTile,
  previewRequest,
  pendingKey,
  targetFromBlock,
  validateCheckIn,
  type CheckInTarget,
} from './checkIn'

const ESSAY: CheckInTarget = {
  block_id: 'b1',
  title: 'Essay',
  start: '2026-11-17T17:00:00Z', // Tue 9am PST
  end: '2026-11-17T18:00:00Z', // a 1h session
  fixed: false,
  status: 'planned',
  done_min: null,
  on_miss: 'reschedule',
  choices: ['reschedule', 'catch_up', 'skip'],
}
const DURING = '2026-11-17T17:30:00Z'
const AFTER = '2026-11-17T19:00:00Z'

function block(changes: Partial<Block>): Block {
  return {
    id: 'b1',
    item_id: 'i1',
    title: 'Essay',
    start: ESSAY.start,
    end: ESSAY.end,
    fixed: false,
    session: 1,
    sessions: 1,
    placed_min: 60,
    estimate_min: 60,
    editable: true,
    series_id: null,
    checkable: true,
    status: 'planned',
    done_min: null,
    missed_action: null,
    history: false,
    kept: 0,
    deleted: false,
    locked: false,
    on_miss: 'reschedule',
    ...changes,
  }
}

describe('the check-in form', () => {
  it("starts with no answer and the item's own policy for the missed time", () => {
    expect(emptyCheckIn(ESSAY)).toEqual({ answer: null, done: '', action: 'reschedule' })
    expect(emptyCheckIn({ ...ESSAY, on_miss: 'ask' }).action).toBeNull()
  })

  it('starts from the earlier answer when changing it', () => {
    expect(emptyCheckIn({ ...ESSAY, status: 'partial', done_min: 30 })).toMatchObject({ answer: 'partly', done: '30m' })
    expect(emptyCheckIn({ ...ESSAY, status: 'done' }).answer).toBe('yes')
    expect(emptyCheckIn({ ...ESSAY, status: 'unanswered' }).answer).toBeNull()
  })

  it('starts from the earlier choice for the missed time, even for an Ask item', () => {
    const earlier = { ...ESSAY, status: 'partial' as const, done_min: 45, on_miss: 'ask' as const, missed_action: 'reschedule' as const }
    expect(emptyCheckIn(earlier).action).toBe('reschedule')
    expect(emptyCheckIn({ ...earlier, on_miss: 'catch_up', missed_action: 'skip' }).action).toBe('skip')
  })

  it('needs an answer, a part of the session for Partly, and a choice for the missed time', () => {
    expect(validateCheckIn({ answer: null, done: '', action: null }, ESSAY)).toHaveProperty('answer')
    expect(validateCheckIn({ answer: 'yes', done: '', action: null }, ESSAY)).toEqual({})
    expect(validateCheckIn({ answer: 'partly', done: '1h', action: 'skip' }, ESSAY).done).toBe(
      "Use a length shorter than the session's 1h, like 30m.",
    )
    expect(validateCheckIn({ answer: 'partly', done: '45m', action: 'skip' }, ESSAY)).toEqual({})
    expect(validateCheckIn({ answer: 'no', done: '', action: null }, ESSAY)).toHaveProperty('action')
  })

  it('sends what is shown: the length for Partly, the choice for Partly and No', () => {
    expect(checkInRequest({ answer: 'yes', done: '20m', action: 'skip' })).toEqual({ answer: 'yes' })
    expect(checkInRequest({ answer: 'partly', done: '45m', action: 'catch_up' })).toEqual({
      answer: 'partly',
      done_min: 45,
      action: 'catch_up',
    })
    expect(checkInRequest({ answer: 'no', done: '', action: 'skip' }, true)).toEqual({
      answer: 'no',
      action: 'skip',
      accept_shortfall: true,
    })
  })

  it('offers no Reschedule for a fixed block', () => {
    expect(targetFromBlock(block({ fixed: true, on_miss: 'catch_up' })).choices).toEqual(['catch_up', 'skip'])
  })
})

describe('check-in lines and looks', () => {
  it('counts sessions in the banner title', () => {
    expect([bannerTitle(1), bannerTitle(3)]).toEqual(['1 session to check in', '3 sessions to check in'])
  })

  it('waits for a check-in only once a checkable block has ended', () => {
    expect(awaitsCheckIn(block({}), DURING)).toBe(false)
    expect(awaitsCheckIn(block({}), AFTER)).toBe(true)
    expect(awaitsCheckIn(block({ checkable: false }), AFTER)).toBe(false)
    expect(awaitsCheckIn(block({ status: 'done' }), AFTER)).toBe(false)
    expect(canCheckIn(block({}), DURING)).toBe(true) // finished early
  })

  it('says how the session went', () => {
    expect(checkInLine(block({}), DURING)).toBe('')
    expect(checkInLine(block({}), AFTER)).toBe('Waiting for a check-in')
    expect(checkInLine(block({ status: 'done' }), AFTER)).toBe('Done')
    expect(checkInLine(block({ status: 'partial', done_min: 30, missed_action: 'reschedule' }), AFTER)).toBe(
      'Partly done: 30m of 1h · The rest is rescheduled',
    )
    expect(checkInLine(block({ status: 'missed', missed_action: 'catch_up' }), AFTER)).toBe('Missed · Caught up later')
    expect(checkInLine(block({ status: 'unanswered', missed_action: null }), AFTER)).toBe(
      'No answer · Waiting for your choice',
    )
  })

  it('draws finished work as done and missed work as missed', () => {
    expect(blockKind(block({ status: 'partial' }))).toBe('done')
    expect(blockKind(block({ status: 'unanswered' }))).toBe('missed')
    expect(blockKind(block({ fixed: true }))).toBe('fixed')
  })

  it('notices when the server changed the pending list', () => {
    const one = [{ block_id: 'b1', status: 'planned' as const }]
    expect(pendingKey(one)).not.toBe(pendingKey([{ block_id: 'b1', status: 'unanswered' as const }]))
  })
})

describe('the check-in dialog tile', () => {
  const lecture = { ...ESSAY, title: 'Lecture', fixed: true }
  const form = { answer: 'no' as const, done: '', action: 'catch_up' as const }
  const caughtUp: CheckInPreview = {
    action: 'catch_up',
    missed_min: 30,
    item_title: 'Lecture',
    due_reason: 'next session',
    recording: true,
    catch_up: {
      id: 'c1', source: null, editable: true, series_id: null, week_start: '2026-11-16', title: 'Catch up: Lecture',
      preset: 'before_deadline', day: null, start_time: null, end_time: null, weekdays: null,
      deadline_date: '2026-11-19', deadline_time: '11:00:00', estimate_min: 45, max_chunk_min: null,
      one_block_per_day: false, keep_length: false, session_min: null, checkable: true, on_miss: 'reschedule',
    },
  }

  it('asks a fixed event whether you went', () => {
    expect([answerQuestion(lecture), answerQuestion(ESSAY)]).toEqual(['Did you go?', 'Did you do it?'])
  })

  it('previews only a complete Partly or No', () => {
    expect(previewRequest(form, ESSAY)).toEqual({ answer: 'no', action: 'catch_up' })
    expect(previewRequest({ ...form, answer: 'partly', done: '' }, ESSAY)).toBeNull()
    expect(previewRequest({ ...form, answer: 'yes' }, ESSAY)).toBeNull()
  })

  it('shows the catch-up item it makes, with the rounding and why it is due then', () => {
    expect(missTile(caughtUp, 15)).toEqual({
      label: 'Creates a catch-up item',
      title: 'Catch up: Lecture',
      rows: [
        ['Estimate', '45m (30m missed × 1.25 for a recording, rounded up to 15m)'],
        ['Due', 'Before Thu, Nov 19, 11:00am (next session)'],
        ['Placed in', 'Your usual work frames'],
      ],
    })
    expect(missTile({ ...caughtUp, action: 'skip', catch_up: null }, 15)?.text).toBe(
      'The 30m is only logged. Nothing is placed again.',
    )
  })

  it('says when an unanswered session counts as missed', () => {
    expect(graceLine(ESSAY, 'America/Los_Angeles', AFTER)).toBe(
      'No answer by 2:00pm counts as missed. You can change it later.',
    )
    expect(graceLine({ ...ESSAY, status: 'done' }, 'America/Los_Angeles', AFTER)).toBeNull()
  })
})

describe('+15 min', () => {
  const session = block({ fixed: false, start: '2026-11-17T22:00:00Z', end: '2026-11-17T23:00:00Z' })
  const during = '2026-11-17T22:30:00Z'
  const after = '2026-11-17T23:10:00Z'

  it('is offered on a work session that started and has no answer yet, running or just ended', () => {
    expect([canExtend(session, during), canExtend(session, after)]).toEqual([true, true])
  })

  it('is offered on a session without check-ins only while it runs, since it never gets an answer', () => {
    const plain = { ...session, checkable: false }
    expect([canExtend(plain, during), canExtend(plain, after)]).toEqual([true, false])
  })

  it('is offered on a running fixed event too, where it moves the end', () => {
    const lecture: Block = { ...session, fixed: true }
    expect(canExtend(lecture, during)).toBe(true)
  })

  it('is offered before it starts too', () => {
    expect(canExtend(session, '2026-11-17T21:00:00Z')).toBe(true)
  })

  it('is not offered once answered, or on kept records', () => {
    expect(canExtend({ ...session, status: 'done' }, after)).toBe(false)
    expect(canExtend({ ...session, deleted: true }, during)).toBe(false)
  })

  it('names one slot of the slot setting', () => {
    expect([extendLabel(15), extendLabel(30), extendLabel(60)]).toEqual(['+15 min', '+30 min', '+1h'])
  })
})
