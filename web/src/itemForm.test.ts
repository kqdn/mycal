import { describe, expect, it } from 'vitest'
import {
  emptyForm,
  parseDuration,
  showsEstimate,
  showsOneSessionPerDay,
  summary,
  toRequest,
  validate,
  type ItemForm,
} from './itemForm'

const LA = 'America/Los_Angeles'
const WEEK = '2026-11-16'
const SUNDAY_BEFORE = '2026-11-15T20:00:00Z' // Sun Nov 15, 12pm PST

function form(changes: Partial<ItemForm>): ItemForm {
  return { ...emptyForm(WEEK, '2026-11-15'), title: 'Gym', ...changes }
}

describe('parseDuration', () => {
  it('reads minutes, hours and both', () => {
    expect(['45m', '2h', '1h 30m', '1h30m', '90', ' 2H ', '0h 15m'].map(parseDuration)).toEqual([45, 120, 90, 90, 90, 120, 15])
  })

  it('refuses anything else', () => {
    expect(['', 'abc', '1.5h', '0', '0m', 'h', '30 minutes'].map(parseDuration)).toEqual([null, null, null, null, null, null, null])
  })
})

describe('emptyForm', () => {
  it('starts on today when today is in the week, else on its Monday', () => {
    expect(emptyForm(WEEK, '2026-11-18').day).toBe('2026-11-18')
    expect(emptyForm(WEEK, '2026-11-15').day).toBe(WEEK)
    expect(emptyForm(WEEK, '2026-11-15')).toMatchObject({ preset: 'days', weekdays: [], dueTime: '23:59' })
  })
})

describe('validate', () => {
  const errors = (changes: Partial<ItemForm>) => validate(form(changes), SUNDAY_BEFORE, LA)

  it('accepts a complete item of each kind', () => {
    expect(errors({ preset: 'days', weekdays: [0, 2], estimate: '3h' })).toEqual({})
    expect(errors({ preset: 'day', day: '2026-11-18', estimate: '45m' })).toEqual({})
    expect(errors({ preset: 'day_range', day: '2026-11-19', startTime: '17:00', endTime: '21:00', estimate: '30m' })).toEqual({})
    expect(errors({ preset: 'exact', day: '2026-11-19', startTime: '23:00', endTime: '01:00' })).toEqual({}) // overnight
    expect(errors({ preset: 'before_deadline', dueDate: '2026-11-20', dueTime: '17:00', estimate: '4h' })).toEqual({})
  })

  it('explains what is missing or wrong', () => {
    expect(errors({ title: '  ', preset: 'days', weekdays: [0], estimate: '1h' }).title).toBe('Give the item a title.')
    expect(errors({ preset: 'days', estimate: '1h' }).weekdays).toBe('Pick at least one day.')
    expect(errors({ preset: 'days', weekdays: [0], estimate: '1h', startTime: '16:00' }).times).toBe('Give both times, or neither.')
    expect(errors({ preset: 'day_range', estimate: '1h', startTime: '16:00', endTime: '16:00' }).times).toBe(
      'The start and end times are the same.',
    )
    expect(errors({ preset: 'days', weekdays: [0], estimate: 'soon' }).estimate).toBe('Use a length like 45m or 1h 30m.')
    expect(errors({ preset: 'days', weekdays: [0], estimate: '1h', longestSession: 'x' }).longestSession).toBe(
      'Use a length like 45m or 1h 30m.',
    )
    expect(errors({ preset: 'before_deadline', dueDate: '2026-11-15', dueTime: '11:00', estimate: '1h' }).due).toBe(
      'That deadline has already passed.',
    )
  })

  it('needs no estimate for an exact-time item', () => {
    expect(errors({ preset: 'exact', day: '2026-11-19', startTime: '09:00', endTime: '10:00', estimate: '' })).toEqual({})
  })
})

describe('what shows', () => {
  it('hides the estimate for exact-time items', () => {
    expect(showsEstimate(form({ preset: 'exact' }))).toBe(false)
    expect(showsEstimate(form({ preset: 'day' }))).toBe(true)
  })

  it('shows one session per day only when the work splits into sessions', () => {
    expect(showsOneSessionPerDay(form({ estimate: '3h', longestSession: '1h' }))).toBe(true)
    expect(showsOneSessionPerDay(form({ estimate: '1h', longestSession: '1h' }))).toBe(false)
    expect(showsOneSessionPerDay(form({ estimate: '3h', longestSession: '' }))).toBe(false)
    expect(showsOneSessionPerDay(form({ preset: 'exact', estimate: '3h', longestSession: '1h' }))).toBe(false)
  })
})

describe('toRequest', () => {
  it('sends a days item for the viewed week', () => {
    const request = toRequest(
      form({ weekdays: [4, 0, 2], startTime: '16:00', endTime: '21:00', estimate: '3h', longestSession: '1h', oneSessionPerDay: true }),
      WEEK,
    )
    expect(request).toEqual({
      week_start: WEEK,
      title: 'Gym',
      preset: 'days',
      weekdays: [0, 2, 4],
      start_time: '16:00',
      end_time: '21:00',
      estimate_min: 180,
      max_chunk_min: 60,
      one_block_per_day: true,
    })
  })

  it('leaves out hidden fields', () => {
    // A switch that no longer shows (one session) and an estimate on an exact item are not sent.
    expect(toRequest(form({ estimate: '1h', longestSession: '', oneSessionPerDay: true }), WEEK).one_block_per_day).toBe(false)
    const exact = toRequest(form({ preset: 'exact', day: '2026-11-19', startTime: '09:00', endTime: '10:00', estimate: '2h' }), WEEK)
    expect(exact).toEqual({
      week_start: WEEK,
      title: 'Gym',
      preset: 'exact',
      day: '2026-11-19',
      start_time: '09:00',
      end_time: '10:00',
      one_block_per_day: false,
    })
  })

  it('sends a deadline as a local date and time', () => {
    const request = toRequest(form({ preset: 'before_deadline', dueDate: '2026-11-20', dueTime: '17:00', estimate: '4h' }), WEEK)
    expect(request).toMatchObject({ deadline_date: '2026-11-20', deadline_time: '17:00', estimate_min: 240 })
    expect(request.day).toBeUndefined()
  })
})

describe('summary', () => {
  const line = (changes: Partial<ItemForm>) => summary(form(changes), WEEK)

  it('names the week for a days item', () => {
    expect(line({ weekdays: [0, 2, 4], startTime: '16:00', endTime: '21:00' })).toBe(
      'The solver sees: Mon, Wed, Fri this week (Nov 16 to 22), 4:00 to 9:00pm',
    )
    expect(line({ weekdays: [5] })).toBe('The solver sees: Sat this week (Nov 16 to 22), in your work hours')
  })

  it('says when a range ends the next day', () => {
    expect(line({ preset: 'day_range', day: '2026-11-19', startTime: '23:00', endTime: '01:00' })).toBe(
      'Thu, Nov 19, 11:00pm to 1:00am (ends the next day)',
    )
  })

  it('describes a day and a deadline', () => {
    expect(line({ preset: 'day', day: '2026-11-18' })).toBe('Any time in your work hours on Wed, Nov 18')
    expect(line({ preset: 'before_deadline', dueDate: '2026-11-18', dueTime: '23:59' })).toBe('Due Wed, Nov 18 at 11:59pm')
  })

  it('says nothing until there is enough to say', () => {
    expect(line({ weekdays: [] })).toBe('')
    expect(line({ preset: 'exact', day: '2026-11-19', startTime: '09:00', endTime: '' })).toBe('')
  })
})
