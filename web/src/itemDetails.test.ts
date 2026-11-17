import { describe, expect, it } from 'vitest'
import type { Block, Week } from './api'
import { confirmLine, kindLine, popoverPosition, unscheduledLine, weekAfterDelete, whenLine } from './itemDetails'

const LA = 'America/Los_Angeles'

function block(changes: Partial<Block>): Block {
  return {
    id: 'b1',
    item_id: 'i1',
    title: 'Gym',
    start: '2026-11-17T22:00:00Z', // Tue Nov 17, 2pm PST
    end: '2026-11-17T22:30:00Z',
    fixed: false,
    session: 1,
    sessions: 1,
    placed_min: 30,
    estimate_min: 30,
    editable: true,
    series_id: null,
    ...changes,
  }
}

const BEFORE = '2026-11-16T08:00:00Z' // Mon Nov 16, 12am PST

describe('whenLine', () => {
  it('gives the day and the range', () => {
    expect(whenLine(block({}), LA)).toBe('Tue, Nov 17, 2:00 to 2:30pm')
  })

  it('says when a block ends the next day', () => {
    // Fri Nov 20, 5pm to Sat 2am PST
    expect(whenLine(block({ start: '2026-11-21T01:00:00Z', end: '2026-11-21T10:00:00Z' }), LA)).toBe(
      'Fri, Nov 20, 5:00pm to 2:00am (ends the next day)',
    )
  })

  it("doesn't call ending at midnight the next day", () => {
    expect(whenLine(block({ start: '2026-11-17T06:00:00Z', end: '2026-11-17T08:00:00Z' }), LA)).toBe(
      'Mon, Nov 16, 10:00pm to 12:00am',
    )
  })
})

describe('kindLine', () => {
  it('names the kind of a single session', () => {
    expect(kindLine(block({}), BEFORE)).toBe('Placed by the solver')
    expect(kindLine(block({ fixed: true, estimate_min: null }), BEFORE)).toBe('Fixed')
  })

  it('says "in all" only when all the work is placed', () => {
    expect(kindLine(block({ session: 2, sessions: 4, placed_min: 120, estimate_min: 120 }), BEFORE)).toBe(
      'Placed by the solver · Session 2 of 4 · 2h in all',
    )
    expect(kindLine(block({ session: 2, sessions: 2, placed_min: 120, estimate_min: 240 }), BEFORE)).toBe(
      'Placed by the solver · Session 2 of 2 · 2h of 4h placed',
    )
  })

  it('says how much is placed even for one session when work is waiting', () => {
    expect(kindLine(block({ placed_min: 60, estimate_min: 55 * 60 }), BEFORE)).toBe('Placed by the solver · 1h of 55h placed')
  })

  it('marks a block that already started', () => {
    expect(kindLine(block({}), '2026-11-17T22:10:00Z')).toBe('Placed by the solver · Already started')
  })
})

describe('unscheduledLine and confirmLine', () => {
  it('gives the reason, or why there are no times, then the estimate', () => {
    const waiting = { title: 'Report', estimate_min: 720, reason: "Waiting on Nov 30 to Dec 6, which can't be planned.", sessions: 0, editable: true }
    expect(unscheduledLine(waiting)).toBe("Waiting on Nov 30 to Dec 6, which can't be planned. · 12h")
    expect(unscheduledLine({ ...waiting, reason: null, estimate_min: 15 })).toBe('Not scheduled: it has no times to go in yet · 15m')
    expect(unscheduledLine({ ...waiting, reason: null, estimate_min: null })).toBe('Not scheduled: it has no times to go in yet')
  })

  it('says what a delete takes', () => {
    expect([0, 1, 4].map(confirmLine)).toEqual([
      'It has no sessions yet.',
      'Its one session goes.',
      'All 4 sessions go, in every week.',
    ])
  })
})

describe('popoverPosition', () => {
  const size = { width: 300, height: 160 }
  const window_ = { width: 1300, height: 900 }

  it('goes right of a block when there is room', () => {
    const anchor = { left: 100, top: 300, right: 250, bottom: 350 }
    expect(popoverPosition(anchor, size, window_, 'beside')).toEqual({ left: 258, top: 300 })
  })

  it('flips to the left near the right edge', () => {
    const anchor = { left: 1050, top: 300, right: 1200, bottom: 350 }
    expect(popoverPosition(anchor, size, window_, 'beside')).toEqual({ left: 742, top: 300 })
  })

  it('stays 16px inside the window at the top and bottom', () => {
    expect(popoverPosition({ left: 100, top: 2, right: 250, bottom: 20 }, size, window_, 'beside').top).toBe(16)
    expect(popoverPosition({ left: 100, top: 850, right: 250, bottom: 880 }, size, window_, 'beside').top).toBe(724)
  })

  it('fits a narrow window', () => {
    const narrow = { width: 340, height: 700 }
    expect(popoverPosition({ left: 60, top: 200, right: 120, bottom: 240 }, size, narrow, 'beside')).toEqual({ left: 16, top: 200 })
  })

  it("goes under a row's button, right-aligned, or above it near the bottom", () => {
    expect(popoverPosition({ left: 1200, top: 500, right: 1244, bottom: 544 }, size, window_, 'below')).toEqual({ left: 944, top: 552 })
    expect(popoverPosition({ left: 1200, top: 800, right: 1244, bottom: 844 }, size, window_, 'below')).toEqual({ left: 944, top: 632 })
  })
})

describe('weekAfterDelete', () => {
  const week = { week_start: '2026-11-16' } as Week

  it('shows the returned week while it is still being viewed', () => {
    expect(weekAfterDelete('2026-11-16', week)).toBe(week)
  })

  it('leaves the display alone after navigating away', () => {
    expect(weekAfterDelete('2026-11-23', week)).toBeNull()
  })
})
