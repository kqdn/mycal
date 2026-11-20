import { describe, expect, it } from 'vitest'
import type { Block, Proposal, Week } from './api'
import { changedBlocks, checkInProposes, overlapLines, proposalChanges, shownWeek } from './proposal'

const LA = 'America/Los_Angeles'

// Times are PST (UTC-8): 2026-11-19T02:00Z is Wed, Nov 18, 6:00pm.
function block(id: string, title: string, start: string, end: string): Block {
  return {
    id, item_id: `item-${id}`, title, start, end, fixed: false, session: 1, sessions: 1, placed_min: 60,
    estimate_min: 60, editable: true, series_id: null, checkable: true, status: 'planned', done_min: null,
    missed_action: null, history: false, on_miss: 'reschedule', kept: 0, deleted: false,
  }
}

const GYM = block('g', 'Gym', '2026-11-19T02:00:00Z', '2026-11-19T03:00:00Z') // Wed 6:00 to 7:00pm
const READ = block('r', 'Read', '2026-11-18T22:00:00Z', '2026-11-19T00:00:00Z') // Wed 2:00 to 4:00pm

describe('proposalChanges', () => {
  it('lists nothing when the proposal keeps every block', () => {
    expect(proposalChanges([GYM, READ], [READ, GYM], LA)).toEqual([])
  })

  it('names a move by its old and new day and time, with a length change', () => {
    const moved = { ...GYM, start: '2026-11-20T00:30:00Z', end: '2026-11-20T01:00:00Z' } // Thu 4:30 to 5:00pm
    expect(proposalChanges([GYM], [moved], LA)).toEqual([
      { blockId: 'g', title: 'Gym', kind: 'moved', text: 'Moves from Wed 6:00pm to Thu 4:30pm · 1h becomes 30m' },
    ])
  })

  it('says a block that keeps its start only changes length', () => {
    const shorter = { ...READ, end: '2026-11-18T23:30:00Z' }
    expect(proposalChanges([READ], [shorter], LA)).toEqual([
      { blockId: 'r', title: 'Read', kind: 'resized', text: '2h becomes 1h 30m' },
    ])
  })

  it('lists new and removed blocks in the order they come in the week', () => {
    const essay = block('e', 'Essay', '2026-11-18T17:00:00Z', '2026-11-18T18:00:00Z') // Wed 9:00 to 10:00am
    expect(proposalChanges([GYM, READ], [READ, essay], LA)).toEqual([
      { blockId: 'e', title: 'Essay', kind: 'new', text: 'New · Wed, Nov 18, 9:00 to 10:00am' },
      { blockId: 'g', title: 'Gym', kind: 'removed', text: 'Off this week · was Wed, Nov 18, 6:00 to 7:00pm' },
    ])
  })
})

const PROPOSAL: Proposal = { summary: 'Add Essay', blocks: [READ], unscheduled: [], left_over: [], overlaps: [] }

describe('shownWeek', () => {
  const week = { blocks: [GYM], unscheduled: [], proposal: PROPOSAL } as unknown as Week

  it("shows the proposal's blocks unless the current plan is picked", () => {
    expect(shownWeek(week, true).blocks).toEqual([READ])
    expect(shownWeek(week, false).blocks).toEqual([GYM])
    expect(shownWeek({ ...week, proposal: null }, true).blocks).toEqual([GYM])
  })
})

describe('changedBlocks', () => {
  it('gives a moved block in both plans, and leaves out blocks that stay', () => {
    const moved = { ...GYM, start: '2026-11-20T00:30:00Z', end: '2026-11-20T01:00:00Z' }
    const week = { blocks: [GYM, READ], timezone: LA, proposal: { ...PROPOSAL, blocks: [moved, READ] } } as unknown as Week
    expect(changedBlocks(week)).toEqual([GYM, moved])
  })
})

describe('overlapLines', () => {
  it('names both blocks of each overlapping pair', () => {
    expect(overlapLines({ ...PROPOSAL, blocks: [GYM, READ], overlaps: [['r', 'g']] })).toEqual(['Read and Gym overlap'])
  })
})

describe('checkInProposes', () => {
  it('proposes only answers that move work', () => {
    expect(checkInProposes({ answer: 'yes' }, 'reschedule')).toBe(false)
    expect(checkInProposes({ answer: 'no' }, 'reschedule')).toBe(true)
    expect(checkInProposes({ answer: 'partly', done_min: 30 }, 'catch_up')).toBe(true)
    expect(checkInProposes({ answer: 'no' }, 'skip')).toBe(false)
    expect(checkInProposes({ answer: 'no', action: 'skip' }, 'ask')).toBe(false)
    expect(checkInProposes({ answer: 'no', action: 'catch_up' }, 'ask')).toBe(true)
  })
})
