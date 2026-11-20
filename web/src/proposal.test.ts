import { describe, expect, it } from 'vitest'
import type { Block, Proposal, Week } from './api'
import { changeCount, changedBlocks, checkInProposes, otherSpot, overlapLines, proposalChanges, shownWeek } from './proposal'

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

  it('names a move to another day with both days, a right arrow and a length change', () => {
    const moved = { ...GYM, start: '2026-11-20T00:30:00Z', end: '2026-11-20T01:00:00Z' } // Thu 4:30 to 5:00pm
    expect(proposalChanges([GYM], [moved], LA)).toEqual([
      {
        blockId: 'g', title: 'Gym', kind: 'moved', text: 'Moves from Wed 6:00pm to Thu 4:30pm · 1h becomes 30m',
        before: GYM, after: moved, tagProposal: 'From Wed 6:00pm', tagCurrent: 'To Thu 4:30pm', arrow: 'right',
      },
    ])
  })

  it('says a block that keeps its start only changes length', () => {
    const shorter = { ...READ, end: '2026-11-18T23:30:00Z' }
    expect(proposalChanges([READ], [shorter], LA)).toEqual([
      {
        blockId: 'r', title: 'Read', kind: 'resized', text: '2h becomes 1h 30m', before: READ, after: shorter,
        tagProposal: 'Was 2h', tagCurrent: 'Becomes 1h 30m', arrow: null,
      },
    ])
  })

  it('lists new and removed blocks in the order they come in the week', () => {
    const essay = block('e', 'Essay', '2026-11-18T17:00:00Z', '2026-11-18T18:00:00Z') // Wed 9:00 to 10:00am
    expect(proposalChanges([GYM, READ], [READ, essay], LA)).toMatchObject([
      { blockId: 'e', kind: 'new', text: 'New · Wed, Nov 18, 9:00 to 10:00am', tagProposal: 'New', tagCurrent: null },
      { blockId: 'g', kind: 'removed', text: 'Off this week · was Wed, Nov 18, 6:00 to 7:00pm', tagProposal: null, tagCurrent: 'Off this week' },
    ])
  })

  it('matches by block, so sessions of one item are told apart', () => {
    // Prototype v4's sample week (Nov 16 to 22): three Gym sessions of one item, two of which move.
    const { current, preview } = prototypeWeek()
    expect(proposalChanges(current, preview, LA).map(({ blockId, text, tagProposal, tagCurrent, arrow }) => ({ blockId, text, tagProposal, tagCurrent, arrow }))).toEqual([
      { blockId: 'gymMon', text: 'Moves from Mon 5:00pm to 6:00pm', tagProposal: 'From 5:00pm', tagCurrent: 'To 6:00pm', arrow: 'down' },
      { blockId: 'gymThu', text: 'Moves from Thu 6:00pm to 4:30pm', tagProposal: 'From 6:00pm', tagCurrent: 'To 4:30pm', arrow: 'up' },
      { blockId: 'p46', text: 'Moves from Fri 2:00pm to 10:00am', tagProposal: 'From 2:00pm', tagCurrent: 'To 10:00am', arrow: 'up' },
      { blockId: 'labRead', text: 'Moves from Thu 4:30pm to Fri 4:00pm', tagProposal: 'From Thu 4:30pm', tagCurrent: 'To Fri 4:00pm', arrow: 'right' },
    ])
  })
})

describe('otherSpot', () => {
  const { current, preview } = prototypeWeek()
  const [, gymThu] = proposalChanges(current, preview, LA)

  it('shows where a change was in the proposal, and where it goes in the current plan', () => {
    expect(otherSpot(gymThu, true)).toEqual({ span: current.find((b) => b.id === 'gymThu'), label: 'Was here' })
    expect(otherSpot(gymThu, false)).toEqual({ span: preview.find((b) => b.id === 'gymThu'), label: 'Moves here' })
  })

  it('names the other length of a block that only changes length', () => {
    const shorter = { ...READ, end: '2026-11-18T23:30:00Z' }
    const [resized] = proposalChanges([READ], [shorter], LA)
    expect(otherSpot(resized, true)).toEqual({ span: READ, label: 'Was 2h' })
    expect(otherSpot(resized, false)).toEqual({ span: shorter, label: 'Becomes 1h 30m' })
  })

  it('has no other spot for a block only one plan has', () => {
    const [added] = proposalChanges([], [GYM], LA)
    expect(otherSpot(added, true)).toBeNull()
    expect(otherSpot(added, false)).toEqual({ span: GYM, label: 'Moves here' })
  })
})

describe('changeCount', () => {
  it('counts changes', () => {
    expect(changeCount(1)).toBe('1 change from your current plan')
    expect(changeCount(4)).toBe('4 changes from your current plan')
  })
})

/** Local LA time on Nov `day`, 2026 (PST, UTC-8), from an hour like 16.5 for 4:30pm. */
function at(day: number, hour: number): string {
  return new Date(Date.UTC(2026, 10, day, 8) + hour * 3_600_000).toISOString().replace('.000Z', 'Z')
}

/** The sample week of prototype v4, as the current plan and the previewed one. */
function prototypeWeek(): { current: Block[]; preview: Block[] } {
  const rows: [string, string, number, number, number, [number, number, number]?][] = [
    ['gymMon', 'Gym', 16, 17, 18, [16, 18, 19]],
    ['cs70Tue', 'CS 70 lecture', 17, 11, 12.5],
    ['labMeet', 'Lab meeting', 18, 14, 15],
    ['gymWed', 'Gym', 18, 17, 18],
    ['notes', 'Read lecture notes', 19, 9, 10],
    ['lecture', 'CS 70 lecture', 19, 11, 12.5],
    ['p13', 'Problems 1 to 3', 19, 14, 16],
    ['gymThu', 'Gym', 19, 18, 19, [19, 16.5, 17.5]],
    ['labRead', 'Lab reading', 19, 16.5, 17.25, [20, 16, 16.75]],
    ['p46', 'Problems 4 to 6', 20, 14, 16, [20, 10, 12]],
    ['write', 'Write up and submit', 21, 11, 12],
  ]
  const item = (title: string) => title.toLowerCase().replaceAll(' ', '-') // the three Gyms share one item
  const current = rows.map(([id, title, day, s, e]) => ({ ...block(id, title, at(day, s), at(day, e)), item_id: item(title) }))
  const preview = rows.map(([id, title, day, s, e, moved]) => {
    const [d, ps, pe] = moved ?? [day, s, e]
    return { ...block(id, title, at(d, ps), at(d, pe)), item_id: item(title) }
  })
  return { current, preview }
}

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
