import { describe, expect, it } from 'vitest'
import { addDays, clock, dayLabel, mondayOf, toLocal } from './time'

const LA = 'America/Los_Angeles'

describe('toLocal', () => {
  it('uses the given timezone, not the browser one', () => {
    expect(toLocal('2026-11-18T05:00:00Z', LA)).toEqual({ date: '2026-11-17', minutes: 21 * 60 })
    expect(toLocal('2026-11-18T05:00:00Z', 'Asia/Tokyo')).toEqual({ date: '2026-11-18', minutes: 14 * 60 })
  })

  it('keeps wall-clock time across the DST change', () => {
    // 9am on Sat Oct 31 (PDT, UTC-7) and on Sun Nov 1 (PST, UTC-8).
    expect(toLocal('2026-10-31T16:00:00Z', LA)).toEqual({ date: '2026-10-31', minutes: 540 })
    expect(toLocal('2026-11-01T17:00:00Z', LA)).toEqual({ date: '2026-11-01', minutes: 540 })
  })
})

describe('dates', () => {
  it('adds days across a month end', () => {
    expect(addDays('2026-11-30', 1)).toBe('2026-12-01')
    expect(addDays('2026-11-16', -7)).toBe('2026-11-09')
  })

  it('finds the Monday of a week', () => {
    expect(mondayOf('2026-11-16')).toBe('2026-11-16')
    expect(mondayOf('2026-11-22')).toBe('2026-11-16')
    expect(mondayOf('2026-11-23')).toBe('2026-11-23')
  })

  it('formats labels', () => {
    expect(dayLabel('2026-11-16')).toBe('Mon, Nov 16')
    expect(clock(21 * 60 + 15)).toBe('21:15')
    expect(clock(1440)).toBe('24:00')
  })
})
