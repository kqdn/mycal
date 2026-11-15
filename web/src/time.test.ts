import { describe, expect, it } from 'vitest'
import { addDays, estimateLabel, hourLabel, mondayOf, range12, time12, toLocal, weekTitle } from './time'

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
})

describe('12-hour times', () => {
  it('formats a single time', () => {
    expect(time12(14 * 60)).toBe('2:00pm')
    expect(time12(9 * 60 + 5)).toBe('9:05am')
    expect(time12(12 * 60)).toBe('12:00pm')
    expect(time12(0)).toBe('12:00am')
    expect(time12(1440)).toBe('12:00am') // the end of the day
  })

  it('drops the first am/pm only when both match', () => {
    expect(range12(14 * 60, 15 * 60 + 30)).toBe('2:00 to 3:30pm')
    expect(range12(9 * 60, 11 * 60)).toBe('9:00 to 11:00am')
    expect(range12(11 * 60, 12 * 60 + 30)).toBe('11:00am to 12:30pm')
    expect(range12(17 * 60, 2 * 60)).toBe('5:00pm to 2:00am') // overnight
    expect(range12(22 * 60, 1440)).toBe('10:00pm to 12:00am')
  })

  it('labels hours', () => {
    expect([0, 8, 12, 13, 23].map(hourLabel)).toEqual(['12am', '8am', '12pm', '1pm', '11pm'])
  })
})

describe('titles and estimates', () => {
  it('titles a week', () => {
    expect(weekTitle('2026-11-16')).toBe('Nov 16 to 22')
    expect(weekTitle('2026-11-30')).toBe('Nov 30 to Dec 6')
  })

  it('formats estimates', () => {
    expect([15, 60, 90, 125].map(estimateLabel)).toEqual(['15m', '1h', '1h 30m', '2h 5m'])
  })
})
