import { describe, expect, it } from 'vitest'
import type { RepeatOut, SeriesFormOut } from './api'
import { emptyForm, type ItemForm } from './itemForm'
import {
  chooseRepeat,
  fitRepeat,
  formFromSeries,
  repeatChoices,
  repeatLine,
  repeatPhrase,
  repeatSummary,
  toSeriesRequest,
  validateWithRepeat,
  weekdayOf,
} from './repeatForm'

const LA = 'America/Los_Angeles'
const WEEK = '2026-11-16'
const TODAY = '2026-11-17' // a Tuesday
const NOW = '2026-11-17T20:00:00Z' // Tue Nov 17, 12pm PST

function form(changes: Partial<ItemForm>): ItemForm {
  return { ...emptyForm(WEEK, TODAY), title: 'Office hours', ...changes }
}

const OFFICE_HOURS = form({
  preset: 'exact',
  startTime: '08:00',
  endTime: '09:00',
  repeat: 'weekly',
  repeatDays: [1, 4],
  startDate: TODAY,
})

const errorsOf = (f: ItemForm, startUnchanged = false) => validateWithRepeat(f, NOW, LA, undefined, false, TODAY, startUnchanged)

describe('repeat choices', () => {
  it('offers Never, Weekly and Daily, but only Every week for a days item', () => {
    expect(repeatChoices('exact', false).map((c) => c.label)).toEqual(['Never', 'Weekly', 'Daily'])
    expect(repeatChoices('every_day', false).map((c) => c.label)).toEqual(['Never', 'Every week'])
  })

  it('leaves out Never when editing a series', () => {
    expect(repeatChoices('exact', true).map((c) => c.value)).toEqual(['weekly', 'daily'])
  })

  it("starts a weekly series on its start date's weekday", () => {
    expect(weekdayOf('2026-11-16')).toBe(0)
    expect(weekdayOf('2026-11-22')).toBe(6)
    expect(chooseRepeat(form({ startDate: '2026-11-19' }), 'weekly')).toEqual({ repeat: 'weekly', repeatDays: [3] })
    expect(chooseRepeat(form({ repeatDays: [0] }), 'weekly')).toEqual({ repeat: 'weekly' })
  })

  it('turns Daily into Weekly when the preset changes to a days item', () => {
    expect(fitRepeat(form({ preset: 'days', repeat: 'daily' })).repeat).toBe('weekly')
    expect(fitRepeat(form({ preset: 'day', repeat: 'daily' })).repeat).toBe('daily')
  })
})

describe('validateWithRepeat', () => {
  it('accepts a valid weekly series without the hidden date fields', () => {
    expect(errorsOf({ ...OFFICE_HOURS, day: '' })).toEqual({})
  })

  it('checks the repeat fields', () => {
    expect(errorsOf({ ...OFFICE_HOURS, repeatDays: [] }).repeatDays).toBe('Pick at least one day to repeat on.')
    expect(errorsOf({ ...OFFICE_HOURS, interval: '0' }).interval).toBe('Use a whole number of 1 or more.')
    expect(errorsOf({ ...OFFICE_HOURS, interval: '1.5' }).interval).toBe('Use a whole number of 1 or more.')
    expect(errorsOf({ ...OFFICE_HOURS, endDate: '2026-11-01' }).endDate).toBe('The end date is before the start date.')
  })

  it("refuses a start in the past, unless editing a series without moving its start", () => {
    const past = { ...OFFICE_HOURS, startDate: '2026-11-16' }
    expect(errorsOf(past).startDate).toBe("A repeating item can't start in the past.")
    expect(errorsOf(past, true).startDate).toBeUndefined()
  })

  it("lets a days item start anywhere in this week, since it repeats by the week", () => {
    const days = form({ preset: 'days', weekdays: [0, 2], estimate: '1h', repeat: 'weekly', startDate: '2026-11-16' })
    expect(errorsOf(days)).toEqual({})
    expect(errorsOf({ ...days, startDate: '2026-11-15' }).startDate).toBe("A repeating item can't start in the past.")
  })

  it('needs only a due time for a repeating deadline', () => {
    const due = form({ preset: 'before_deadline', estimate: '1h', repeat: 'weekly', repeatDays: [2], dueDate: '2026-11-01' })
    expect(errorsOf(due)).toEqual({})
    expect(errorsOf({ ...due, dueTime: '' }).due).toBe('Pick a due time.')
  })

  it('leaves a one-off item to the normal checks', () => {
    expect(errorsOf(form({ preset: 'day', estimate: '1h', day: '' })).day).toBe('Pick a date.')
  })
})

describe('toSeriesRequest', () => {
  it('sends the rule and leaves out the date fields', () => {
    expect(toSeriesRequest({ ...OFFICE_HOURS, endDate: '2026-12-18' }, WEEK)).toEqual({
      week_start: WEEK,
      title: 'Office hours',
      preset: 'exact',
      start_time: '08:00',
      end_time: '09:00',
      one_block_per_day: false,
      freq: 'weekly',
      interval: 1,
      repeat_weekdays: [1, 4],
      start_date: TODAY,
      end_date: '2026-12-18',
    })
  })

  it('sends no repeat days for a days item or a daily series', () => {
    const days = form({ preset: 'every_day', weekdays: [0, 1], eachDay: '30m', repeat: 'weekly', repeatDays: [3] })
    expect(toSeriesRequest(days, WEEK).repeat_weekdays).toEqual([])
    expect(toSeriesRequest({ ...OFFICE_HOURS, repeat: 'daily', interval: '2' }, WEEK)).toMatchObject({
      freq: 'daily',
      interval: 2,
      repeat_weekdays: [],
    })
  })
})

describe('repeat lines', () => {
  const rule = (changes: Partial<RepeatOut>): RepeatOut => ({
    id: 's1',
    freq: 'weekly',
    interval: 1,
    weekdays: [1, 4],
    per_week: false,
    end_date: null,
    ...changes,
  })

  it('says how it repeats', () => {
    expect(repeatPhrase(rule({}))).toBe('every Tue and Fri')
    expect(repeatPhrase(rule({ weekdays: [0, 2, 4] }))).toBe('every Mon, Wed and Fri')
    expect(repeatPhrase(rule({ interval: 2, weekdays: [1] }))).toBe('every 2 weeks on Tue')
    expect(repeatPhrase(rule({ per_week: true, weekdays: [] }))).toBe('every week')
    expect(repeatPhrase(rule({ freq: 'daily', weekdays: [] }))).toBe('every day')
    expect(repeatPhrase(rule({ freq: 'daily', interval: 3, weekdays: [] }))).toBe('every 3 days')
  })

  it('adds the end date in the popover', () => {
    expect(repeatLine(rule({}))).toBe('Repeats every Tue and Fri')
    expect(repeatLine(rule({ end_date: '2026-12-18' }))).toBe('Repeats every Tue and Fri until Fri, Dec 18')
  })

  it('sums up a repeating form', () => {
    expect(repeatSummary(OFFICE_HOURS)).toBe('Every Tue and Fri, 8:00 to 9:00am, from Tue, Nov 17')
    expect(repeatSummary({ ...OFFICE_HOURS, repeatDays: [] })).toBe('')
    const piano = form({ preset: 'every_day', weekdays: [0, 1, 2, 3, 4], startTime: '18:00', endTime: '20:00', repeat: 'weekly', startDate: TODAY })
    expect(repeatSummary(piano)).toBe('Each of Mon, Tue, Wed, Thu and Fri, every week, 6:00 to 8:00pm, from Mon, Nov 16')
    const due = form({ preset: 'before_deadline', dueTime: '17:00', repeat: 'weekly', repeatDays: [2], startDate: TODAY, endDate: '2026-12-16' })
    expect(repeatSummary(due)).toBe('Due every Wed at 5:00pm, from Tue, Nov 17 until Wed, Dec 16')
  })
})

describe('formFromSeries', () => {
  it('fills the form from a stored series', () => {
    const stored: SeriesFormOut = {
      id: 's1',
      source: null,
      title: 'Office hours',
      preset: 'exact',
      start_time: '08:00:00',
      end_time: '09:00:00',
      weekdays: null,
      deadline_time: null,
      estimate_min: null,
      max_chunk_min: null,
      one_block_per_day: false,
      session_min: null,
      freq: 'weekly',
      interval: 1,
      repeat_weekdays: [1, 4],
      start_date: TODAY,
      end_date: null,
    }
    const filled = formFromSeries(stored, TODAY)
    expect(filled).toMatchObject({
      title: 'Office hours',
      preset: 'exact',
      startTime: '08:00',
      endTime: '09:00',
      repeat: 'weekly',
      interval: '1',
      repeatDays: [1, 4],
      startDate: TODAY,
      endDate: '',
    })
    expect(toSeriesRequest(filled, WEEK)).toEqual(toSeriesRequest(OFFICE_HOURS, WEEK))
  })
})
