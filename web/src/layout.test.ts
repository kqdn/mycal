import { describe, expect, it } from 'vitest'
import { earliestMinute, pieces } from './layout'

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

describe('earliestMinute', () => {
  it('ignores the tail of a night from the day before', () => {
    const spans = [
      { start: '2026-11-21T01:00:00Z', end: '2026-11-21T10:00:00Z' }, // Fri 5pm to Sat 2am
      { start: '2026-11-17T19:00:00Z', end: '2026-11-17T20:00:00Z' }, // Tue 11am
    ]
    expect(earliestMinute(spans, WEEK, LA)).toBe(11 * 60)
  })

  it('is null for an empty week', () => {
    expect(earliestMinute([], WEEK, LA)).toBeNull()
  })
})
