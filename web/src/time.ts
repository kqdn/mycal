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

/** "Mon Nov 16" style label for a date string. */
export function dayLabel(date: DateString): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString('en-US', {
    timeZone: 'UTC',
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

/** "21:00" from minutes since midnight; 1440 shows as "24:00". */
export function clock(minutes: number): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`
}
