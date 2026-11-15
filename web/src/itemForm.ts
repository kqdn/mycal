// The New item form as pure logic: parsing lengths, validating fields,
// building the API request and the "what the solver sees" summary line.
// The dialog (NewItemDialog.tsx) only renders this. See web/DESIGN.md,
// "Add item dialog".

import { addDays, dayName, estimateLabel, range12, time12, toLocal, weekTitle, type DateString } from './time'

export type Preset = 'exact' | 'day' | 'day_range' | 'days' | 'every_day' | 'before_deadline'

export const PRESETS: { value: Preset; label: string }[] = [
  { value: 'exact', label: 'Exact time' },
  { value: 'day', label: 'Any time on a day' },
  { value: 'day_range', label: 'Time range on a day' },
  { value: 'days', label: 'Any of these days' },
  { value: 'every_day', label: 'Every one of these days' },
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
  eachDay: string // an every-day item's length on each day, same format as estimate
}

export type Field = 'title' | 'day' | 'times' | 'weekdays' | 'due' | 'estimate' | 'longestSession' | 'eachDay'

/** What the form needs to know which picked days are still open: now (UTC ISO), the week's timezone and work frames. */
export interface DayContext {
  now: string
  timezone: string
  frames: { start: string; end: string }[] // the week's work-frame time, UTC
}
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
  session_min?: number
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
    eachDay: '',
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

export const showsEstimate = (form: ItemForm) => form.preset !== 'exact' && form.preset !== 'every_day'
export const showsEachDay = (form: ItemForm) => form.preset === 'every_day'
const picksDays = (form: ItemForm) => form.preset === 'days' || form.preset === 'every_day'
export const usesTimes = (form: ItemForm) => form.preset === 'exact' || form.preset === 'day_range' || picksDays(form)

/** The one-session-per-day switch only matters when the work splits into more than one session. */
export function showsOneSessionPerDay(form: ItemForm): boolean {
  if (!showsEstimate(form)) return false
  const estimate = parseDuration(form.estimate)
  const longest = parseDuration(form.longestSession)
  return estimate !== null && longest !== null && longest < estimate
}

/** Field errors, worded to say how to fix them. `now` is a UTC ISO time; `timezone` is the week's.
 * With `week` (the viewed week and its frames), an every-day item with no open day left is an error too. */
export function validate(
  form: ItemForm,
  now: string,
  timezone: string,
  week?: { weekStart: DateString; frames: DayContext['frames'] },
): Errors {
  const errors: Errors = {}
  if (!form.title.trim()) errors.title = 'Give the item a title.'

  if (form.preset === 'exact' || form.preset === 'day' || form.preset === 'day_range') {
    if (!form.day) errors.day = 'Pick a date.'
  }
  if (form.preset === 'exact' || form.preset === 'day_range') {
    if (!form.startTime || !form.endTime) errors.times = 'Give a start and an end time.'
  }
  if (picksDays(form)) {
    if (form.weekdays.length === 0) errors.weekdays = 'Pick at least one day.'
    else if (form.preset === 'every_day' && week && openDays(form, week.weekStart, { now, timezone, frames: week.frames }).length === 0) {
      errors.weekdays = 'None of these days has room left this week.'
    }
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
  if (showsEachDay(form) && parseDuration(form.eachDay) === null) {
    errors.eachDay = 'Use a length like 30m or 1h.'
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
  if (picksDays(form)) request.weekdays = [...form.weekdays].sort((a, b) => a - b)
  if (form.preset === 'before_deadline') {
    request.deadline_date = form.dueDate
    request.deadline_time = form.dueTime
  }
  if (showsEstimate(form)) {
    request.estimate_min = parseDuration(form.estimate) ?? undefined
    const longest = parseDuration(form.longestSession)
    if (longest !== null) request.max_chunk_min = longest
  }
  if (showsEachDay(form)) request.session_min = parseDuration(form.eachDay) ?? undefined
  return request
}

/** The line under a preset's fields saying what the solver will get, or '' until there is enough to say.
 * An every-day item lists only its open days, so it needs `context`. */
export function summary(form: ItemForm, weekStart: DateString, context?: DayContext): string {
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
    case 'every_day': {
      if (!context) return ''
      const open = openDays(form, weekStart, context)
      if (open.length === 0) return ''
      const days = open.map((d) => WEEKDAYS[d]).join(', ')
      const session = parseDuration(form.eachDay)
      const range = timeRange()
      const when = range ? `, ${range}` : ', in your work hours'
      const each = session === null ? `each of ${days}` : `${estimateLabel(session)} on each of ${days}`
      return `The solver sees: ${each} this week (${weekTitle(weekStart)})${when}`
    }
    case 'before_deadline': {
      if (!form.dueDate || !form.dueTime) return ''
      return `Due ${dayName(form.dueDate)} at ${time12(minutes(form.dueTime))}`
    }
  }
}

const DAY_MIN = 24 * 60

/**
 * The picked weekdays (0 = Monday) that still have room for one whole session after now,
 * the same rule as the planner's effective_item. A day's allowed time is the
 * "Only between" range (cut at midnight; an overnight range's tail counts for the
 * next day only if that day is picked too) or else the week's work frames.
 * Without a valid length, a day is open if any of its time is left.
 * The server checks again on add, and its answer wins.
 */
export function openDays(form: ItemForm, weekStart: DateString, context: DayContext): number[] {
  const session = parseDuration(form.eachDay) ?? 1
  const current = toLocal(context.now, context.timezone)
  const picked = [...new Set(form.weekdays)].sort((a, b) => a - b)
  const frameTime = form.startTime && form.endTime ? null : localIntervals(context.frames, context.timezone)
  return picked.filter((weekday) => {
    const date = addDays(weekStart, weekday)
    if (date < current.date) return false
    const from = date === current.date ? current.minutes : 0
    const intervals = frameTime ? (frameTime.get(date) ?? []) : rangeIntervals(form, weekday, picked)
    return intervals.some(([start, end]) => end - Math.max(start, from) >= session)
  })
}

/**
 * Whether any part of a flexible item's time range falls outside the work frames on the days
 * it applies to. Informational only: a range overrides the frames (PRD decision log), so this
 * never blocks adding. False when there is no complete range, no picked day, or (for a time
 * range on a day) a date outside the viewed week, whose frames the page doesn't have.
 */
export function outsideWorkHours(form: ItemForm, weekStart: DateString, context: DayContext): boolean {
  if (form.preset !== 'day_range' && !picksDays(form)) return false
  if (!form.startTime || !form.endTime || form.startTime === form.endTime) return false
  const dates =
    form.preset === 'day_range'
      ? [form.day].filter((d) => d >= weekStart && d <= addDays(weekStart, 6))
      : [...new Set(form.weekdays)].map((d) => addDays(weekStart, d))
  const frames = localIntervals(context.frames, context.timezone)
  const [sh, sm] = form.startTime.split(':').map(Number)
  const [eh, em] = form.endTime.split(':').map(Number)
  const start = sh * 60 + sm
  const end = eh * 60 + em
  const inside = (date: DateString, from: number, to: number) =>
    (frames.get(date) ?? []).some(([a, b]) => a <= from && to <= b)
  return dates.some((date) =>
    end > start ? !inside(date, start, end) : !inside(date, start, DAY_MIN) || !inside(addDays(date, 1), 0, end),
  )
}

/** An "Only between" range on one picked day, in minutes since its midnight. */
function rangeIntervals(form: ItemForm, weekday: number, picked: number[]): [number, number][] {
  const [sh, sm] = form.startTime.split(':').map(Number)
  const [eh, em] = form.endTime.split(':').map(Number)
  const start = sh * 60 + sm
  const end = eh * 60 + em
  if (end > start) return [[start, end]]
  const intervals: [number, number][] = [[start, DAY_MIN]]
  if (picked.includes(weekday - 1)) intervals.push([0, end]) // yesterday's range runs past midnight
  return intervals
}

/** UTC spans as local [start, end) minutes per local date, split at midnight. */
function localIntervals(spans: DayContext['frames'], timezone: string): Map<DateString, [number, number][]> {
  const byDate = new Map<DateString, [number, number][]>()
  const add = (date: DateString, start: number, end: number) => {
    if (end > start) byDate.set(date, [...(byDate.get(date) ?? []), [start, end]])
  }
  for (const span of spans) {
    const start = toLocal(span.start, timezone)
    const end = toLocal(span.end, timezone)
    let date = start.date
    let from = start.minutes
    while (date < end.date) {
      add(date, from, DAY_MIN)
      date = addDays(date, 1)
      from = 0
    }
    add(date, from, end.minutes)
  }
  return byDate
}
