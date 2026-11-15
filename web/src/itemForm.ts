// The New item form as pure logic: parsing lengths, validating fields,
// building the API request and the "what the solver sees" summary line.
// The dialog (NewItemDialog.tsx) only renders this. See web/DESIGN.md,
// "Add item dialog".

import { addDays, range12, time12, toLocal, weekTitle, weekdayShort, type DateString } from './time'

export type Preset = 'exact' | 'day' | 'day_range' | 'days' | 'before_deadline'

export const PRESETS: { value: Preset; label: string }[] = [
  { value: 'exact', label: 'Exact time' },
  { value: 'day', label: 'Any time on a day' },
  { value: 'day_range', label: 'Time range on a day' },
  { value: 'days', label: 'Any of these days' },
  { value: 'before_deadline', label: 'Before a deadline' },
]

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Everything the form holds, as typed. Times are "HH:MM" from <input type="time">. */
export interface ItemForm {
  title: string
  preset: Preset
  day: DateString
  startTime: string
  endTime: string
  weekdays: number[] // 0 = Monday
  dueDate: DateString
  dueTime: string
  estimate: string // "1h 30m", "45m", "2h" or minutes
  longestSession: string // same format; empty means no limit
  oneSessionPerDay: boolean
}

export type Field = 'title' | 'day' | 'times' | 'weekdays' | 'due' | 'estimate' | 'longestSession'
export type Errors = Partial<Record<Field, string>>

/** The request body for POST /api/items (solver/src/mycal/api.py, ItemIn). */
export interface ItemRequest {
  week_start: DateString
  title: string
  preset: Preset
  day?: DateString
  start_time?: string
  end_time?: string
  weekdays?: number[]
  deadline_date?: DateString
  deadline_time?: string
  estimate_min?: number
  max_chunk_min?: number
  one_block_per_day: boolean
}

/** A fresh form for the viewed week: dates default to today if it is in that week, else its Monday. */
export function emptyForm(weekStart: DateString, today: DateString): ItemForm {
  const inWeek = today >= weekStart && today <= addDays(weekStart, 6)
  const day = inWeek ? today : weekStart
  return {
    title: '',
    preset: 'days',
    day,
    startTime: '',
    endTime: '',
    weekdays: [],
    dueDate: day,
    dueTime: '23:59',
    estimate: '',
    longestSession: '',
    oneSessionPerDay: false,
  }
}

/** Minutes from "45m", "2h", "1h 30m", "1h30m" or a plain number of minutes; null if it isn't a length. */
export function parseDuration(text: string): number | null {
  const s = text.trim().toLowerCase()
  if (/^\d+$/.test(s)) return Number(s) > 0 ? Number(s) : null
  const match = /^(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?$/.exec(s)
  if (!match || (match[1] === undefined && match[2] === undefined)) return null
  const minutes = Number(match[1] ?? 0) * 60 + Number(match[2] ?? 0)
  return minutes > 0 ? minutes : null
}

export const showsEstimate = (form: ItemForm) => form.preset !== 'exact'
export const usesTimes = (form: ItemForm) => form.preset === 'exact' || form.preset === 'day_range' || form.preset === 'days'

/** The one-session-per-day switch only matters when the work splits into more than one session. */
export function showsOneSessionPerDay(form: ItemForm): boolean {
  if (!showsEstimate(form)) return false
  const estimate = parseDuration(form.estimate)
  const longest = parseDuration(form.longestSession)
  return estimate !== null && longest !== null && longest < estimate
}

/** Field errors, worded to say how to fix them. `now` is a UTC ISO time; `timezone` is the week's. */
export function validate(form: ItemForm, now: string, timezone: string): Errors {
  const errors: Errors = {}
  if (!form.title.trim()) errors.title = 'Give the item a title.'

  if (form.preset === 'exact' || form.preset === 'day' || form.preset === 'day_range') {
    if (!form.day) errors.day = 'Pick a date.'
  }
  if (form.preset === 'exact' || form.preset === 'day_range') {
    if (!form.startTime || !form.endTime) errors.times = 'Give a start and an end time.'
  }
  if (form.preset === 'days') {
    if (form.weekdays.length === 0) errors.weekdays = 'Pick at least one day.'
    if (Boolean(form.startTime) !== Boolean(form.endTime)) errors.times = 'Give both times, or neither.'
  }
  if (usesTimes(form) && form.startTime && form.startTime === form.endTime) {
    errors.times = 'The start and end times are the same.'
  }
  if (form.preset === 'before_deadline') {
    if (!form.dueDate || !form.dueTime) errors.due = 'Pick a due date and time.'
    else if (isPast(form.dueDate, form.dueTime, now, timezone)) errors.due = 'That deadline has already passed.'
  }

  if (showsEstimate(form) && parseDuration(form.estimate) === null) {
    errors.estimate = 'Use a length like 45m or 1h 30m.'
  }
  if (showsEstimate(form) && form.longestSession.trim() && parseDuration(form.longestSession) === null) {
    errors.longestSession = 'Use a length like 45m or 1h 30m.'
  }
  return errors
}

/** Whether a local date and time in `timezone` is at or before `now`. */
function isPast(date: DateString, time: string, now: string, timezone: string): boolean {
  const current = toLocal(now, timezone)
  const [h, m] = time.split(':').map(Number)
  return date < current.date || (date === current.date && h * 60 + m <= current.minutes)
}

/** The request for a valid form. Hidden fields are left out, so a hidden switch can't sneak in. */
export function toRequest(form: ItemForm, weekStart: DateString): ItemRequest {
  const request: ItemRequest = {
    week_start: weekStart,
    title: form.title.trim(),
    preset: form.preset,
    one_block_per_day: showsOneSessionPerDay(form) && form.oneSessionPerDay,
  }
  if (form.preset === 'exact' || form.preset === 'day' || form.preset === 'day_range') request.day = form.day
  if (usesTimes(form) && form.startTime && form.endTime) {
    request.start_time = form.startTime
    request.end_time = form.endTime
  }
  if (form.preset === 'days') request.weekdays = [...form.weekdays].sort((a, b) => a - b)
  if (form.preset === 'before_deadline') {
    request.deadline_date = form.dueDate
    request.deadline_time = form.dueTime
  }
  if (showsEstimate(form)) {
    request.estimate_min = parseDuration(form.estimate) ?? undefined
    const longest = parseDuration(form.longestSession)
    if (longest !== null) request.max_chunk_min = longest
  }
  return request
}

/** The line under a preset's fields saying what the solver will get, or '' until there is enough to say. */
export function summary(form: ItemForm, weekStart: DateString): string {
  const minutes = (time: string) => {
    const [h, m] = time.split(':').map(Number)
    return h * 60 + m
  }
  const timeRange = () => {
    if (!form.startTime || !form.endTime || form.startTime === form.endTime) return ''
    const start = minutes(form.startTime)
    const end = minutes(form.endTime)
    return range12(start, end) + (end < start ? ' (ends the next day)' : '')
  }

  switch (form.preset) {
    case 'exact':
    case 'day_range': {
      const range = timeRange()
      return form.day && range ? `${dayName(form.day)}, ${range}` : ''
    }
    case 'day':
      return form.day ? `Any time in your work hours on ${dayName(form.day)}` : ''
    case 'days': {
      if (form.weekdays.length === 0) return ''
      const days = [...form.weekdays].sort((a, b) => a - b).map((d) => WEEKDAYS[d]).join(', ')
      const range = timeRange()
      const when = range ? `, ${range}` : ', in your work hours'
      return `The solver sees: ${days} this week (${weekTitle(weekStart)})${when}`
    }
    case 'before_deadline': {
      if (!form.dueDate || !form.dueTime) return ''
      return `Due ${dayName(form.dueDate)} at ${time12(minutes(form.dueTime))}`
    }
  }
}

/** "Wed, Nov 18" */
function dayName(date: DateString): string {
  const month = new Date(`${date}T00:00:00Z`).toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short' })
  return `${weekdayShort(date)}, ${month} ${Number(date.slice(8, 10))}`
}
