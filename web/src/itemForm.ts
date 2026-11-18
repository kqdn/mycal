// The New item form as pure logic: parsing lengths, validating fields,
// building the API request and the "what the solver sees" summary line.
// The dialog (NewItemDialog.tsx) only renders this. See web/DESIGN.md,
// "Add item dialog".

import type { ItemFormOut } from './api'
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

/** What a missed check-in does (the item's on_miss). */
export type OnMiss = 'reschedule' | 'catch_up' | 'skip' | 'ask'

export const MISS_CHOICES: { value: OnMiss; label: string }[] = [
  { value: 'reschedule', label: 'Reschedule' },
  { value: 'catch_up', label: 'Catch up' },
  { value: 'skip', label: 'Skip' },
  { value: 'ask', label: 'Ask me' },
]

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
  checkIn: boolean | null // null: the preset's default (on, except for exact-time items)
  onMiss: OnMiss
  // Repeating (repeatForm.ts). Shown when adding, and when editing a series.
  repeat: 'never' | 'weekly' | 'daily'
  interval: string // every N weeks or days, as typed
  repeatDays: number[] // a weekly series' days, 0 = Monday (not used by days items)
  startDate: DateString
  endDate: DateString // '' for no end
}

export type Field =
  | 'title'
  | 'day'
  | 'times'
  | 'weekdays'
  | 'due'
  | 'repeatDays'
  | 'interval'
  | 'startDate'
  | 'endDate'
  | 'estimate'
  | 'longestSession'
  | 'eachDay'

/** Fields in the order the form shows them, so pressing Add can go to the first error. */
export const FIELDS_IN_ORDER: Field[] = [
  'title',
  'day',
  'weekdays',
  'times',
  'due',
  'repeatDays',
  'interval',
  'startDate',
  'endDate',
  'estimate',
  'longestSession',
  'eachDay',
]

/** The first field with an error, in form order, or undefined if there is none. */
export function firstError(errors: Errors): Field | undefined {
  return FIELDS_IN_ORDER.find((field) => errors[field] !== undefined)
}

/** What the form needs to know which picked days are still open and what lengths are planned:
 * now (UTC ISO), the week's timezone, work frames and slot size. */
export interface DayContext {
  now: string
  timezone: string
  frames: { start: string; end: string }[] // the week's work-frame time, UTC
  slotMin: number
}

/** A length rounded up to the slot grid, as the planner does for estimates and every-day sessions. */
export function plannedUp(minutes: number, slotMin: number): number {
  return Math.ceil(minutes / slotMin) * slotMin
}

/** A longest session rounded down to the slot grid, but never below one slot, as the planner does. */
export function plannedDown(minutes: number, slotMin: number): number {
  return Math.max(1, Math.floor(minutes / slotMin)) * slotMin
}

/** "Planned as 30m" when the planner will use a different length than typed, else undefined. */
export function plannedHint(typed: string, slotMin: number, round: 'up' | 'down'): string | undefined {
  const minutes = parseDuration(typed)
  if (minutes === null) return undefined
  const planned = round === 'up' ? plannedUp(minutes, slotMin) : plannedDown(minutes, slotMin)
  return planned === minutes ? undefined : `Planned as ${estimateLabel(planned)}`
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
  checkable: boolean
  on_miss: OnMiss
  accept_shortfall?: boolean // set when sending again after the "fewer sessions" question
}

/**
 * The form for a stored item (GET /api/items/{id}), the inverse of toRequest. Lengths go back
 * to text as typed ("1h 30m"), and times drop their seconds. Fields the item doesn't use keep
 * the fresh-form defaults for its week, so switching presets while editing starts sensibly.
 */
export function formFrom(item: ItemFormOut, today: DateString): ItemForm {
  const length = (minutes: number | null) => (minutes === null ? '' : estimateLabel(minutes))
  const clock = (time: string | null) => (time === null ? '' : time.slice(0, 5))
  const fresh = emptyForm(item.week_start, today)
  return {
    ...fresh,
    title: item.title,
    preset: item.preset === 'custom' ? fresh.preset : item.preset,
    day: item.day ?? fresh.day,
    startTime: clock(item.start_time),
    endTime: clock(item.end_time),
    weekdays: item.weekdays ?? [],
    dueDate: item.deadline_date ?? fresh.dueDate,
    dueTime: item.deadline_time === null ? fresh.dueTime : clock(item.deadline_time),
    estimate: length(item.estimate_min),
    longestSession: length(item.max_chunk_min),
    oneSessionPerDay: item.one_block_per_day,
    eachDay: length(item.session_min),
    checkIn: item.checkable,
    onMiss: item.on_miss,
    // Made to repeat, it starts from its own date: its day, its due date, or its week.
    startDate: item.day ?? item.deadline_date ?? item.week_start,
  }
}

/** What says when an item can go, as one comparable string; the same fields as the server's _when. */
export function whenKey(form: ItemForm): string {
  const onDay = form.preset === 'exact' || form.preset === 'day' || form.preset === 'day_range'
  return JSON.stringify([
    form.preset,
    onDay ? form.day : null,
    usesTimes(form) ? [form.startTime, form.endTime] : null,
    picksDays(form) ? [...new Set(form.weekdays)].sort((a, b) => a - b) : null,
    form.preset === 'before_deadline' ? [form.dueDate, form.dueTime] : null,
  ])
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
    checkIn: null,
    onMiss: 'reschedule',
    repeat: 'never',
    interval: '1',
    repeatDays: [],
    startDate: day,
    endDate: '',
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

/** Whether a check-in is asked when a session ends: as switched, else on unless it is an exact-time item. */
export function checksIn(form: ItemForm): boolean {
  return form.checkIn ?? form.preset !== 'exact'
}

/** The If missed choices: an exact-time item can't move, so it has no Reschedule. */
export function missChoices(form: ItemForm): { value: OnMiss; label: string }[] {
  return MISS_CHOICES.filter((c) => form.preset !== 'exact' || c.value !== 'reschedule')
}

/** The line under If missed, saying what the choice does. */
export function missHint(policy: OnMiss): string {
  switch (policy) {
    case 'reschedule':
      return 'The missed time goes back into the plan.'
    case 'catch_up':
      return 'Adds a catch-up item, due before the next one.'
    case 'skip':
      return "Nothing moves. It's only logged."
    case 'ask':
      return 'You choose each time.'
  }
}

/** The If missed choice as sent: Reschedule turns into Skip for an exact-time item. */
export function missPolicy(form: ItemForm): OnMiss {
  return form.preset === 'exact' && form.onMiss === 'reschedule' ? 'skip' : form.onMiss
}

/** The one-session-per-day switch only matters when the work splits into more than one session. */
export function showsOneSessionPerDay(form: ItemForm): boolean {
  if (!showsEstimate(form)) return false
  const estimate = parseDuration(form.estimate)
  const longest = parseDuration(form.longestSession)
  return estimate !== null && longest !== null && longest < estimate
}

/** Field errors, worded to say how to fix them. `now` is a UTC ISO time; `timezone` is the week's.
 * With `week` (the viewed week and its frames), an every-day item with no open day left is an error too.
 * With `allowPast` (editing without changing when the item is), a passed deadline or day is allowed,
 * as the server allows it, so a past item's title can still be fixed. */
export function validate(
  form: ItemForm,
  now: string,
  timezone: string,
  week?: { weekStart: DateString; frames: DayContext['frames']; slotMin: number },
  allowPast = false,
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
    else if (form.preset === 'every_day' && week && !allowPast && openDays(form, week.weekStart, { now, timezone, frames: week.frames, slotMin: week.slotMin }).length === 0) {
      errors.weekdays = 'None of these days has room left this week.'
    }
    if (Boolean(form.startTime) !== Boolean(form.endTime)) errors.times = 'Give both times, or neither.'
  }
  if (usesTimes(form) && form.startTime && form.startTime === form.endTime) {
    errors.times = 'The start and end times are the same.'
  }
  if (form.preset === 'before_deadline') {
    if (!form.dueDate || !form.dueTime) errors.due = 'Pick a due date and time.'
    else if (!allowPast && isPast(form.dueDate, form.dueTime, now, timezone)) errors.due = 'That deadline has already passed.'
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
    checkable: checksIn(form),
    on_miss: missPolicy(form),
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
      const typed = parseDuration(form.eachDay)
      const session = typed === null ? null : plannedUp(typed, context.slotMin)
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
 * The length is the planned one (rounded up to the slot), and times are taken
 * on the slot grid: now rounds up, and a range's edges round inward.
 * Without a valid length, a day is open if any of its time is left.
 * The server checks again on add, and its answer wins.
 */
export function openDays(form: ItemForm, weekStart: DateString, context: DayContext): number[] {
  const slot = context.slotMin
  const typed = parseDuration(form.eachDay)
  const session = typed === null ? 1 : plannedUp(typed, slot)
  const current = toLocal(context.now, context.timezone)
  const picked = [...new Set(form.weekdays)].sort((a, b) => a - b)
  const frameTime = form.startTime && form.endTime ? null : localIntervals(context.frames, context.timezone)
  return picked.filter((weekday) => {
    const date = addDays(weekStart, weekday)
    if (date < current.date) return false
    const from = date === current.date ? plannedUp(current.minutes, slot) : 0
    const intervals = frameTime ? (frameTime.get(date) ?? []) : rangeIntervals(form, weekday, picked)
    return intervals.some(
      ([start, end]) => Math.floor(end / slot) * slot - plannedUp(Math.max(start, from), slot) >= session,
    )
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
