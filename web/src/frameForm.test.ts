import { describe, expect, it } from 'vitest'
import {
  dayRange,
  emptyFrameForm,
  firstFrameError,
  frameDetail,
  frameFormFrom,
  frameLabel,
  frameSummary,
  toFrameRequest,
  validateFrame,
  type FrameOut,
} from './frameForm'

const weekdays: FrameOut = { id: 'f1', name: 'Weekdays', weekdays: [0, 1, 2, 3, 4], start_time: '09:00:00', end_time: '18:00:00' }

describe('dayRange', () => {
  it('names runs, pairs, lists and the whole week', () => {
    expect(dayRange([0, 1, 2, 3, 4])).toBe('Mon to Fri')
    expect(dayRange([5, 6])).toBe('Sat and Sun')
    expect(dayRange([0, 2, 4])).toBe('Mon, Wed, Fri')
    expect(dayRange([0, 1])).toBe('Mon and Tue')
    expect(dayRange([3])).toBe('Thu')
    expect(dayRange([6, 5, 4, 3, 2, 1, 0])).toBe('Every day')
  })

  it('lists a broken run instead of spanning it', () => {
    expect(dayRange([0, 1, 3])).toBe('Mon, Tue, Thu')
  })
})

describe('frame rows', () => {
  it('gives days and times, and the accessible name', () => {
    expect(frameDetail(weekdays)).toBe('Mon to Fri · 9:00am to 6:00pm')
    expect(frameLabel(weekdays)).toBe('Edit work frame Weekdays, Mon to Fri, 9:00am to 6:00pm')
  })

  it('says when an overnight frame ends the next day', () => {
    const late: FrameOut = { ...weekdays, weekdays: [4], start_time: '22:00:00', end_time: '01:00:00' }
    expect(frameDetail(late)).toBe('Fri · 10:00pm to 1:00am (ends the next day)')
  })
})

describe('the frame dialog', () => {
  it('fills in from a stored frame and sends it back', () => {
    const form = frameFormFrom(weekdays)
    expect(form).toEqual({ name: 'Weekdays', weekdays: [0, 1, 2, 3, 4], startTime: '09:00', endTime: '18:00' })
    expect(toFrameRequest({ ...form, name: '  Weekdays ', weekdays: [4, 0, 0] })).toEqual({
      name: 'Weekdays',
      weekdays: [0, 4],
      start_time: '09:00',
      end_time: '18:00',
    })
  })

  it('checks each field with the dialog messages, in order', () => {
    const errors = validateFrame({ name: ' ', weekdays: [], startTime: '09:00', endTime: '09:00' })
    expect(errors).toEqual({
      name: 'Give it a name, like Weekdays.',
      weekdays: 'Pick at least one day.',
      times: "Start and end can't be the same time.",
    })
    expect(firstFrameError(errors)).toBe('name')
    expect(validateFrame({ ...emptyFrameForm(), name: 'X', endTime: '' }).times).toBe('Pick a start and an end time.')
    expect(validateFrame({ ...emptyFrameForm(), name: 'X' })).toEqual({})
  })

  it('sums hours per day and per week in the summary line', () => {
    expect(frameSummary(frameFormFrom(weekdays))).toBe('The planner sees: Mon to Fri, 9:00am to 6:00pm, 9h each day (45h a week)')
    const late = { name: 'Late', weekdays: [4], startTime: '22:00', endTime: '01:30' }
    expect(frameSummary(late)).toBe('The planner sees: Fri, 10:00pm to 1:30am (ends the next day), 3h 30m each day (3h 30m a week)')
  })

  it('leaves out the hours until the times are valid', () => {
    expect(frameSummary({ name: '', weekdays: [5, 6], startTime: '10:00', endTime: '10:00' })).toBe('The planner sees: Sat and Sun')
    expect(frameSummary({ name: '', weekdays: [], startTime: '10:00', endTime: '16:00' })).toBe('')
  })
})
