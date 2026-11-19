// Repeating items as pure logic: the Repeats field's choices and errors, the
// series request, the summary line while repeating, and the details popover's
// "Repeats" line. NewItemDialog.tsx and ItemPopover.tsx only render this.
// See web/DESIGN.md, "Repeat (Milestone 6)".

import type { RepeatOut, SeriesFormOut } from './api'
import {
  emptyForm,
  toRequest,
  usesTimes,
  validate,
  WEEKDAYS,
  type DayContext,
  type Errors,
  type ItemForm,
  type ItemRequest,
  type Preset,
} from './itemForm'
import { dayName, estimateLabel, mondayOf, range12, time12, type DateString } from './time'

/** The request body for POST and PUT /api/series (solver/src/mycal/api.py, SeriesIn). */
export interface SeriesRequest extends ItemRequest {
  freq: 'daily' | 'weekly'
  interval: number
  repeat_weekdays: number[]
  start_date: DateString
  end_date?: DateString
  skipped_dates?: DateString[] // editing: the skipped dates to keep; one left out comes back
}

/** A days item ("any of these days", "every one of these days") repeats as a whole week. */
export const perWeek = (preset: Preset) => preset === 'days' || preset === 'every_day'

export const repeats = (form: ItemForm) => form.repeat !== 'never'

/** The Repeats choices for a preset. A days item only repeats every week. */
export function repeatChoices(preset: Preset, editingSeries: boolean): { value: ItemForm['repeat']; label: string }[] {
  const choices: { value: ItemForm['repeat']; label: string }[] = perWeek(preset)
    ? [
        { value: 'never', label: 'Never' },
        { value: 'weekly', label: 'Every week' },
      ]
    : [
        { value: 'never', label: 'Never' },
        { value: 'weekly', label: 'Weekly' },
        { value: 'daily', label: 'Daily' },
      ]
  return editingSeries ? choices.filter((c) => c.value !== 'never') : choices
}

/** A date's weekday, 0 = Monday. */
export function weekdayOf(date: DateString): number {
  const [y, m, d] = date.split('-').map(Number)
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7
}

/** Changes for picking a Repeats choice: a weekly series starts out on its start date's weekday. */
export function chooseRepeat(form: ItemForm, repeat: ItemForm['repeat']): Partial<ItemForm> {
  if (repeat === 'weekly' && form.repeatDays.length === 0) return { repeat, repeatDays: [weekdayOf(form.startDate)] }
  return { repeat }
}

/** A preset change can leave a choice the new preset doesn't offer (Daily on a days item); fall back to Weekly. */
export function fitRepeat(form: ItemForm): ItemForm {
  return form.repeat === 'daily' && perWeek(form.preset) ? { ...form, repeat: 'weekly' } : form
}

/**
 * Every field error, the Repeats field's included. While repeating, the
 * preset's own date and due date are hidden (each occurrence's date fills them
 * in), so their errors are left out, and the start date is checked instead.
 * `startUnchanged` (editing a series without moving its start) allows a start
 * in the past, as the server does.
 */
export function validateWithRepeat(
  form: ItemForm,
  now: string,
  timezone: string,
  week: { weekStart: DateString; frames: DayContext['frames']; slotMin: number } | undefined,
  allowPast: boolean,
  today: DateString,
  startUnchanged = false,
): Errors {
  if (!repeats(form)) return validate(form, now, timezone, week, allowPast)
  const errors = validate({ ...form, day: form.startDate, dueDate: form.startDate }, now, timezone, undefined, true)
  delete errors.day
  if (errors.due) {
    if (form.dueTime) delete errors.due
    else errors.due = 'Pick a due time.'
  }

  if (form.repeat === 'weekly' && !perWeek(form.preset) && form.repeatDays.length === 0) {
    errors.repeatDays = 'Pick at least one day to repeat on.'
  }
  const interval = form.interval.trim()
  if (!/^\d+$/.test(interval) || Number(interval) < 1) errors.interval = 'Use a whole number of 1 or more.'
  if (!form.startDate) errors.startDate = 'Pick a start date.'
  else if (!startUnchanged) {
    const earliest = perWeek(form.preset) ? mondayOf(today) : today
    const start = perWeek(form.preset) ? mondayOf(form.startDate) : form.startDate
    if (start < earliest) errors.startDate = "A repeating item can't start in the past."
  }
  if (form.endDate && form.startDate && form.endDate < form.startDate) {
    errors.endDate = 'The end date is before the start date.'
  }
  return errors
}

/** The series request for a valid repeating form. The preset's own date fields are left out. */
export function toSeriesRequest(form: ItemForm, weekStart: DateString): SeriesRequest {
  const item = toRequest(form, weekStart)
  delete item.day
  delete item.deadline_date
  const request: SeriesRequest = {
    ...item,
    freq: form.repeat === 'daily' ? 'daily' : 'weekly',
    interval: Number(form.interval.trim()),
    repeat_weekdays: form.repeat === 'weekly' && !perWeek(form.preset) ? [...form.repeatDays].sort((a, b) => a - b) : [],
    start_date: form.startDate,
  }
  if (form.endDate) request.end_date = form.endDate
  if (form.skippedDates !== null) request.skipped_dates = form.skippedDates
  return request
}

/** Changes for "Bring back" on a skipped date: it leaves the list, and saving creates that date again. */
export function bringBack(form: ItemForm, date: DateString): Partial<ItemForm> {
  return { skippedDates: (form.skippedDates ?? []).filter((d) => d !== date) }
}

/** "Tue", "Tue and Fri", "Mon, Wed and Fri". */
function dayList(weekdays: number[]): string {
  const names = [...weekdays].sort((a, b) => a - b).map((d) => WEEKDAYS[d])
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** "every Tue and Fri", "every 2 weeks on Tue", "every week", "every day", "every 3 days". */
export function repeatPhrase(rule: Pick<RepeatOut, 'freq' | 'interval' | 'weekdays' | 'per_week'>): string {
  const n = rule.interval
  if (rule.freq === 'daily') return n === 1 ? 'every day' : `every ${n} days`
  if (rule.per_week || rule.weekdays.length === 0) return n === 1 ? 'every week' : `every ${n} weeks`
  return n === 1 ? `every ${dayList(rule.weekdays)}` : `every ${n} weeks on ${dayList(rule.weekdays)}`
}

/** The popover's line: "Repeats every Tue and Fri", plus " until Fri, Dec 18" when it ends. */
export function repeatLine(rule: RepeatOut): string {
  const until = rule.end_date ? ` until ${dayName(rule.end_date)}` : ''
  return `Repeats ${repeatPhrase(rule)}${until}`
}

/**
 * The summary line while repeating, in place of the one-off summary. For
 * example "Every Tue and Fri, 8:00 to 9:00am, from Mon, Nov 16". '' until there
 * is enough to say.
 */
export function repeatSummary(form: ItemForm): string {
  const interval = Number(form.interval.trim())
  if (!form.startDate || !Number.isInteger(interval) || interval < 1) return ''
  const days = form.repeat === 'weekly' && !perWeek(form.preset) ? form.repeatDays : []
  if (form.repeat === 'weekly' && !perWeek(form.preset) && days.length === 0) return ''
  const when = repeatPhrase({ freq: form.repeat === 'daily' ? 'daily' : 'weekly', interval, weekdays: days, per_week: perWeek(form.preset) })
  const minutes = (time: string) => {
    const [h, m] = time.split(':').map(Number)
    return h * 60 + m
  }
  const range =
    usesTimes(form) && form.startTime && form.endTime && form.startTime !== form.endTime
      ? range12(minutes(form.startTime), minutes(form.endTime)) +
        (minutes(form.endTime) < minutes(form.startTime) ? ' (ends the next day)' : '')
      : ''
  const from = perWeek(form.preset) ? mondayOf(form.startDate) : form.startDate
  const bounds = `, from ${dayName(from)}${form.endDate ? ` until ${dayName(form.endDate)}` : ''}`
  const picked = dayList(form.weekdays)

  switch (form.preset) {
    case 'exact':
    case 'day_range':
      return range ? `${capital(when)}, ${range}${bounds}` : ''
    case 'day':
      return `Any time in your work hours, ${when}${bounds}`
    case 'days':
      if (form.weekdays.length === 0) return ''
      return `${picked} ${when}, ${range || 'in your work hours'}${bounds}`
    case 'every_day':
      if (form.weekdays.length === 0) return ''
      return `Each of ${picked}, ${when}, ${range || 'in your work hours'}${bounds}`
    case 'before_deadline':
      return form.dueTime ? `Due ${when} at ${time12(minutes(form.dueTime))}${bounds}` : ''
  }
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The form for a stored series (GET /api/series/{id}): the inverse of toSeriesRequest. */
export function formFromSeries(series: SeriesFormOut, today: DateString): ItemForm {
  const length = (minutes: number | null) => (minutes === null ? '' : estimateLabel(minutes))
  const clock = (time: string | null) => (time === null ? '' : time.slice(0, 5))
  const fresh = emptyForm(mondayOf(today), today)
  return {
    ...fresh,
    title: series.title,
    preset: series.preset,
    day: series.start_date,
    startTime: clock(series.start_time),
    endTime: clock(series.end_time),
    weekdays: series.weekdays ?? [],
    dueDate: series.start_date,
    dueTime: series.deadline_time === null ? fresh.dueTime : clock(series.deadline_time),
    estimate: length(series.estimate_min),
    longestSession: length(series.max_chunk_min),
    oneSessionPerDay: series.one_block_per_day,
    eachDay: length(series.session_min),
    checkIn: series.checkable,
    onMiss: series.on_miss,
    repeat: series.freq,
    interval: String(series.interval),
    repeatDays: series.repeat_weekdays,
    startDate: series.start_date,
    endDate: series.end_date ?? '',
    skippedDates: series.skipped_dates ?? [],
  }
}
