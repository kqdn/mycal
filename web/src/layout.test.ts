import { describe, expect, it } from 'vitest'
import type { Week } from './api'
import { initialScrollMinute, minutesToPx, pieces, textMode } from './layout'

const LA = 'America/Los_Angeles'
const WEEK = '2026-11-16' // Mon; PST is UTC-8 all week

describe('pieces', () => {
  it('puts a block in its local day column', () => {
    // Tue 9pm PST is Wed 05:00 UTC, but it belongs in Tuesday's column.
    expect(pieces({ start: '2026-11-18T05:00:00Z', end: '2026-11-18T06:00:00Z' }, WEEK, LA)).toEqual([
      { day: 1, startMin: 21 * 60, endMin: 22 * 60, continuesBefore: false, continuesAfter: false },
    ])
  })

  it('splits a span that crosses midnight', () => {
    // Fri 5pm to Sat 2am PST.
    expect(pieces({ start: '2026-11-21T01:00:00Z', end: '2026-11-21T10:00:00Z' }, WEEK, LA)).toEqual([
      { day: 4, startMin: 17 * 60, endMin: 1440, continuesBefore: false, continuesAfter: true },
      { day: 5, startMin: 0, endMin: 2 * 60, continuesBefore: true, continuesAfter: false },
    ])
  })

  it('leaves nothing on the next day when a span ends at midnight', () => {
    // Mon 10pm to Tue 12am PST.
    expect(pieces({ start: '2026-11-17T06:00:00Z', end: '2026-11-17T08:00:00Z' }, WEEK, LA)).toEqual([
      { day: 0, startMin: 22 * 60, endMin: 1440, continuesBefore: false, continuesAfter: false },
    ])
  })

  it('keeps only the part inside the week', () => {
    // Sun Nov 15 9pm to Mon Nov 16 1am PST: only Monday's hour shows.
    expect(pieces({ start: '2026-11-16T05:00:00Z', end: '2026-11-16T09:00:00Z' }, WEEK, LA)).toEqual([
      { day: 0, startMin: 0, endMin: 60, continuesBefore: true, continuesAfter: false },
    ])
  })
})

function week(blocks: [string, string][], frames: [string, string][] = []): Week {
  const span = ([start, end]: [string, string]) => ({ start, end })
  return {
    week_start: WEEK,
    timezone: LA,
    slot_min: 15,
    feasible: true,
    blocks: blocks.map(([start, end], i) => ({
      id: `b${i}`,
      item_id: `i${i}`,
      title: 'Block',
      fixed: false,
      session: 1,
      sessions: 1,
      placed_min: 60,
      estimate_min: 60,
      ...span([start, end]),
    })),
    frames: frames.map(span),
    unscheduled: [],
  }
}

describe('initialScrollMinute', () => {
  it('counts weekend mornings the same as weekdays', () => {
    const blocks: [string, string][] = [
      ['2026-11-17T22:00:00Z', '2026-11-17T23:00:00Z'], // Tue 2pm
      ['2026-11-21T19:00:00Z', '2026-11-21T20:00:00Z'], // Sat 11am, the earliest
    ]
    expect(initialScrollMinute(week(blocks))).toBe(10 * 60 + 30)
  })

  it('ignores the tail of a night from the day before', () => {
    const blocks: [string, string][] = [
      ['2026-11-21T01:00:00Z', '2026-11-21T10:00:00Z'], // Fri 5pm to Sat 2am
      ['2026-11-17T19:00:00Z', '2026-11-17T20:00:00Z'], // Tue 11am
    ]
    expect(initialScrollMinute(week(blocks))).toBe(10 * 60 + 30)
  })

  it('never scrolls above midnight', () => {
    expect(initialScrollMinute(week([['2026-11-16T08:15:00Z', '2026-11-16T09:00:00Z']]))).toBe(0) // Mon 12:15am
  })

  it('uses the earliest work frame when there are no blocks', () => {
    const frames: [string, string][] = [
      ['2026-11-16T22:00:00Z', '2026-11-17T03:00:00Z'], // Mon 2pm to 7pm
      ['2026-11-21T19:00:00Z', '2026-11-22T03:00:00Z'], // Sat 11am to 7pm
    ]
    expect(initialScrollMinute(week([], frames))).toBe(10 * 60 + 30)
  })

  it('starts at the top of an empty week', () => {
    expect(initialScrollMinute(week([]))).toBe(0)
  })
})

describe('textMode', () => {
  it('shows two lines from 1 hour, one line at 30 and 45 min, the title only at 15 min', () => {
    expect(textMode(minutesToPx(15))).toBe('title-only') // 13px
    expect(textMode(minutesToPx(30))).toBe('one-line') // 26px
    expect(textMode(minutesToPx(45))).toBe('one-line') // 39px
    expect(textMode(minutesToPx(60))).toBe('two-line') // 52px
  })

  it('switches at 20px and 40px', () => {
    expect([19, 20, 39, 40].map(textMode)).toEqual(['title-only', 'one-line', 'one-line', 'two-line'])
  })
})
