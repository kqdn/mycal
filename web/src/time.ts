// Date and time helpers. The API sends UTC; these turn it into wall-clock
// time in the week's own timezone (not the browser's), using Intl so no date
// library is needed.

/** A calendar date as "YYYY-MM-DD", with no time or timezone attached. */
export type DateString = string

export interface LocalMoment {
  date: DateString
  minutes: number // minutes since local midnight, 0 to 1439
}

const formatters = new Map<string, Intl.DateTimeFormat>()

function formatterFor(timeZone: string): Intl.DateTimeFormat {
  let formatter = formatters.get(timeZone)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
    formatters.set(timeZone, formatter)
  }
  return formatter
}

/** The local date and minute of a UTC ISO time in `timeZone`. */
export function toLocal(iso: string, timeZone: string): LocalMoment {
  const parts: Record<string, string> = {}
  for (const part of formatterFor(timeZone).formatToParts(new Date(iso))) {
    parts[part.type] = part.value
  }
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  }
}

/**
 * The UTC ISO time of a local date and minute in `timeZone`, the reverse of toLocal. It guesses
 * with the wall-clock time as if it were UTC, then corrects by how far off toLocal says it is
 * (twice, so a guess on the other side of a DST change settles too).
 */
export function fromLocal(date: DateString, minutes: number, timeZone: string): string {
  const [y, m, d] = date.split('-').map(Number)
  const wanted = Date.UTC(y, m - 1, d, 0, minutes)
  let guess = wanted
  for (let i = 0; i < 2; i++) {
    const local = toLocal(new Date(guess).toISOString(), timeZone)
    const [ly, lm, ld] = local.date.split('-').map(Number)
    guess += wanted - Date.UTC(ly, lm - 1, ld, 0, local.minutes)
  }
  return new Date(guess).toISOString()
}

/** Plain calendar arithmetic on a date string (no timezone, so no DST surprises). */
export function addDays(date: DateString, days: number): DateString {
  const [y, m, d] = date.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

/** The Monday on or before `date`. */
export function mondayOf(date: DateString): DateString {
  const [y, m, d] = date.split('-').map(Number)
  const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7 // 0 = Monday
  return addDays(date, -weekday)
}

/** Today's date where the browser is. */
export function today(): DateString {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

// 12-hour times, as web/DESIGN.md sets them: "2:00pm", "2:00 to 3:30pm",
// "11:00am to 12:30pm", hour labels "8am". Minutes count from local midnight;
// 1440 (the end of the day) reads as "12:00am".

function parts12(minutes: number): { clock: string; meridiem: 'am' | 'pm'; hour: number } {
  const total = minutes % 1440
  const h24 = Math.floor(total / 60)
  const hour = h24 % 12 === 0 ? 12 : h24 % 12
  const clock = `${hour}:${String(total % 60).padStart(2, '0')}`
  return { clock, meridiem: h24 < 12 ? 'am' : 'pm', hour }
}

/** "2:00pm" */
export function time12(minutes: number): string {
  const { clock, meridiem } = parts12(minutes)
  return clock + meridiem
}

/** "2:00 to 3:30pm", or "11:00am to 12:30pm" when the am/pm differ. */
export function range12(startMin: number, endMin: number): string {
  const start = parts12(startMin)
  const end = parts12(endMin)
  const first = start.meridiem === end.meridiem ? start.clock : start.clock + start.meridiem
  return `${first} to ${end.clock}${end.meridiem}`
}

/** Hour label for the grid: "8am", "12pm", "12am". */
export function hourLabel(hour: number): string {
  const { hour: h, meridiem } = parts12(hour * 60)
  return `${h}${meridiem}`
}

/** Page title for a week: "Nov 16 to 22", or "Nov 30 to Dec 6" across months. */
export function weekTitle(weekStart: DateString): string {
  const month = (date: DateString) =>
    new Date(`${date}T00:00:00Z`).toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short' })
  const day = (date: DateString) => Number(date.slice(8, 10))
  const end = addDays(weekStart, 6)
  const endText = month(end) === month(weekStart) ? `${day(end)}` : `${month(end)} ${day(end)}`
  return `${month(weekStart)} ${day(weekStart)} to ${endText}`
}

/** "Wed, Nov 18" */
export function dayName(date: DateString): string {
  const month = new Date(`${date}T00:00:00Z`).toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short' })
  return `${weekdayShort(date)}, ${month} ${Number(date.slice(8, 10))}`
}

/** Short weekday for a date: "Mon". */
export function weekdayShort(date: DateString): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'short' })
}

/** "15m", "1h", "1h 30m" */
export function estimateLabel(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m}m`
  return m === 0 ? `${h}h` : `${h}h ${m}m`
}
