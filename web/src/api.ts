// Types matching GET /api/weeks/{week_start} in solver/src/mycal/api.py.
// All times are UTC ISO strings.

import type { DateString } from './time'

export interface Block {
  id: string
  item_id: string
  title: string
  start: string
  end: string
  fixed: boolean // an exact event, not work the solver placed
}

export interface Week {
  week_start: DateString
  timezone: string
  feasible: boolean
  blocks: Block[]
  frames: { start: string; end: string }[]
  unscheduled: { id: string; title: string; estimate_min: number | null }[]
}

/** Why a week could not be shown: no file for it, or a file the API could not use. */
export class WeekError extends Error {
  readonly kind: 'missing' | 'invalid'

  constructor(kind: 'missing' | 'invalid', message: string) {
    super(message)
    this.kind = kind
  }
}

// Weeks fetched this page session (a stopgap until Milestone 3 storage). The
// promise map shares one request between callers; the plain map lets a render
// read an already-loaded week synchronously, so going back shows no loading flash.
const pending = new Map<DateString, Promise<Week>>()
const loaded = new Map<DateString, Week>()

/** The week from memory, or fetched once. A failed fetch is forgotten, so it retries next time. */
export function loadWeek(weekStart: DateString): Promise<Week> {
  let promise = pending.get(weekStart)
  if (!promise) {
    promise = fetchWeek(weekStart).then(
      (week) => {
        loaded.set(weekStart, week)
        return week
      },
      (error: unknown) => {
        pending.delete(weekStart)
        throw error
      },
    )
    pending.set(weekStart, promise)
  }
  return promise
}

/** An already-loaded week, without waiting. */
export function peekWeek(weekStart: DateString): Week | undefined {
  return loaded.get(weekStart)
}

/** Drop everything in memory. For tests. */
export function clearWeekCache(): void {
  pending.clear()
  loaded.clear()
}

export async function fetchWeek(weekStart: DateString): Promise<Week> {
  const response = await fetch(`/api/weeks/${weekStart}`)
  if (response.ok) return response.json()
  if (response.status === 404) throw new WeekError('missing', `No week file for ${weekStart}.`)
  const body = await response.json().catch(() => null)
  const detail = typeof body?.detail === 'string' ? body.detail : response.statusText
  throw new WeekError('invalid', detail || `HTTP ${response.status}`)
}
