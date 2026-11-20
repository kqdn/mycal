import { describe, expect, it } from 'vitest'
import type { Block } from './api'
import { canDrag, dropAt } from './drag'

const LA = 'America/Los_Angeles'
const NOW = '2026-11-16T16:00:00Z' // Mon Nov 16, 8am PST

// Times are PST (UTC-8): 2026-11-17T22:00Z is Tue Nov 17, 2pm.
function block(id: string, title: string, start: string, end: string, changes: Partial<Block> = {}): Block {
  return {
    id, item_id: `item-${id}`, title, start, end, fixed: false, locked: false, session: 1, sessions: 1, placed_min: 60,
    estimate_min: 60, editable: true, series_id: null, checkable: true, status: 'planned', done_min: null,
    missed_action: null, history: false, on_miss: 'reschedule', kept: 0, deleted: false, ...changes,
  }
}

const READ = block('r', 'Read', '2026-11-17T22:00:00Z', '2026-11-17T23:00:00Z') // Tue 2 to 3pm

describe('canDrag', () => {
  it('lets a work session that has not started be dragged', () => {
    expect(canDrag(READ, NOW)).toBe(true)
    expect(canDrag({ ...READ, locked: true }, NOW)).toBe(true)
  })

  it('keeps fixed events, started and finished sessions and kept records where they are', () => {
    expect(canDrag({ ...READ, fixed: true }, NOW)).toBe(false)
    expect(canDrag(READ, READ.start)).toBe(false)
    expect(canDrag({ ...READ, status: 'done' }, NOW)).toBe(false)
    expect(canDrag({ ...READ, deleted: true }, NOW)).toBe(false)
  })
})

describe('dropAt', () => {
  it('keeps the length and turns the local spot into UTC', () => {
    expect(dropAt(READ, '2026-11-18', 9 * 60, [READ], LA, NOW)).toEqual({
      start: '2026-11-18T17:00:00.000Z',
      end: '2026-11-18T18:00:00.000Z',
      problem: null,
      late: false,
    })
  })

  it('warns, without refusing, when it would end after the item is due', () => {
    const due = { ...READ, due: '2026-11-18T18:00:00Z' } // Wed 10am
    expect(dropAt(due, '2026-11-18', 9 * 60, [due], LA, NOW)).toMatchObject({ problem: null, late: false })
    expect(dropAt(due, '2026-11-18', 9 * 60 + 15, [due], LA, NOW)).toMatchObject({ problem: null, late: true })
  })

  it('may land on a session the planner placed, which moves out of the way', () => {
    const gym = block('g', 'Gym', '2026-11-18T17:30:00Z', '2026-11-18T18:30:00Z')
    expect(dropAt(READ, '2026-11-18', 9 * 60, [READ, gym], LA, NOW).problem).toBeNull()
  })

  it('names what is in the way when the spot is kept', () => {
    const at = (other: Block) => dropAt(READ, '2026-11-18', 9 * 60, [READ, other], LA, NOW).problem
    const spot = ['2026-11-18T17:30:00Z', '2026-11-18T18:30:00Z'] as const
    expect(at(block('l', 'Lecture', ...spot, { fixed: true }))).toBe('Lecture is there')
    expect(at(block('c', 'Call', ...spot, { locked: true }))).toBe('Call is there')
    expect(at(block('d', 'Essay', ...spot, { status: 'done' }))).toBe('Essay is there')
  })

  it('touching end to end is not in the way', () => {
    const lecture = block('l', 'Lecture', '2026-11-18T18:00:00Z', '2026-11-18T19:00:00Z', { fixed: true })
    expect(dropAt(READ, '2026-11-18', 9 * 60, [READ, lecture], LA, NOW).problem).toBeNull()
  })

  it('refuses the past', () => {
    expect(dropAt(READ, '2026-11-16', 7 * 60, [READ], LA, NOW).problem).toBe('Already past')
  })
})
