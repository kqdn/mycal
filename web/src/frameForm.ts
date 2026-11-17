// Work frames as pure logic: the Frame dialog's form, its validation and the
// text the Frames and rules page shows. FrameDialog.tsx and RulesPage.tsx only
// render this. See web/DESIGN.md, "Frames and rules".

import { WEEKDAYS } from './itemForm'
import { estimateLabel, range12 } from './time'

/** GET /api/frames: a work frame. Times are local "HH:MM:SS"; 0 = Monday. */
export interface FrameOut {
  id: string
  name: string
  weekdays: number[]
  start_time: string
  end_time: string
}

/** The body of POST and PUT /api/frames. */
export interface FrameRequest {
  name: string
  weekdays: number[]
  start_time: string
  end_time: string
}

/** The dialog's fields as typed. Times are "HH:MM", as time inputs give them. */
export interface FrameForm {
  name: string
  weekdays: number[]
  startTime: string
  endTime: string
}

export type FrameField = 'name' | 'weekdays' | 'times'
export type FrameErrors = Partial<Record<FrameField, string>>
const FIELDS_IN_ORDER: FrameField[] = ['name', 'weekdays', 'times']

export function emptyFrameForm(): FrameForm {
  return { name: '', weekdays: [0, 1, 2, 3, 4], startTime: '09:00', endTime: '17:00' }
}

export function frameFormFrom(frame: FrameOut): FrameForm {
  return {
    name: frame.name,
    weekdays: [...frame.weekdays],
    startTime: frame.start_time.slice(0, 5),
    endTime: frame.end_time.slice(0, 5),
  }
}

/** The dialog's messages, as DESIGN.md words them. */
export function validateFrame(form: FrameForm): FrameErrors {
  const errors: FrameErrors = {}
  if (!form.name.trim()) errors.name = 'Give it a name, like Weekdays.'
  if (form.weekdays.length === 0) errors.weekdays = 'Pick at least one day.'
  if (!form.startTime || !form.endTime) errors.times = 'Pick a start and an end time.'
  else if (form.startTime === form.endTime) errors.times = "Start and end can't be the same time."
  return errors
}

export function firstFrameError(errors: FrameErrors): FrameField | undefined {
  return FIELDS_IN_ORDER.find((field) => errors[field])
}

export function toFrameRequest(form: FrameForm): FrameRequest {
  return {
    name: form.name.trim(),
    weekdays: [...new Set(form.weekdays)].sort((a, b) => a - b),
    start_time: form.startTime,
    end_time: form.endTime,
  }
}

/** Minutes from midnight for "HH:MM" or "HH:MM:SS". */
export function clockMinutes(text: string): number {
  const [h, m] = text.split(':').map(Number)
  return h * 60 + m
}

/**
 * Days as a frame row lists them: "Every day", "Mon to Fri" for three or more
 * in a row, "Sat and Sun" for two, otherwise a list, "Mon, Wed, Fri".
 */
export function dayRange(weekdays: number[]): string {
  const days = [...new Set(weekdays)].sort((a, b) => a - b)
  if (days.length === 7) return 'Every day'
  const consecutive = days.every((day, i) => i === 0 || day === days[i - 1] + 1)
  if (consecutive && days.length >= 3) return `${WEEKDAYS[days[0]]} to ${WEEKDAYS[days[days.length - 1]]}`
  if (days.length === 2) return `${WEEKDAYS[days[0]]} and ${WEEKDAYS[days[1]]}`
  return days.map((day) => WEEKDAYS[day]).join(', ')
}

/** "9:00am to 6:00pm", plus "(ends the next day)" when the end is before the start. */
function frameTimes(startTime: string, endTime: string): string {
  const start = clockMinutes(startTime)
  const end = clockMinutes(endTime)
  return range12(start, end) + (end < start ? ' (ends the next day)' : '')
}

/** A frame row's detail line: "Mon to Fri · 9:00am to 6:00pm". */
export function frameDetail(frame: FrameOut): string {
  return `${dayRange(frame.weekdays)} · ${frameTimes(frame.start_time, frame.end_time)}`
}

/** The row's accessible name: "Edit work frame Weekdays, Mon to Fri, 9:00am to 6:00pm". */
export function frameLabel(frame: FrameOut): string {
  return `Edit work frame ${frame.name}, ${dayRange(frame.weekdays)}, ${frameTimes(frame.start_time, frame.end_time)}`
}

/**
 * The dialog's summary line: "The planner sees: Mon to Fri, 9:00am to 6:00pm,
 * 9h each day (45h a week)". The hours are left out until both times are valid,
 * and the line is empty with no days picked.
 */
export function frameSummary(form: FrameForm): string {
  if (form.weekdays.length === 0) return ''
  const days = dayRange(form.weekdays)
  if (!form.startTime || !form.endTime || form.startTime === form.endTime) return `The planner sees: ${days}`
  const start = clockMinutes(form.startTime)
  const end = clockMinutes(form.endTime)
  const each = (end - start + 1440) % 1440
  const count = new Set(form.weekdays).size
  return `The planner sees: ${days}, ${frameTimes(form.startTime, form.endTime)}, ${estimateLabel(each)} each day (${estimateLabel(each * count)} a week)`
}
