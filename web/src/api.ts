// Types matching GET /api/weeks/{week_start} in solver/src/mycal/api.py.
// All times are UTC ISO strings.

import type { ItemRequest } from './itemForm'
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

/** Why a week could not be shown: nothing imported yet (404), or data the API could not use. */
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
  throw await failure(response)
}

/** The error for a failed response: the server's `detail` sentence, kind by status. */
async function failure(response: Response): Promise<WeekError> {
  const body = await response.json().catch(() => null)
  const detail = typeof body?.detail === 'string' ? body.detail : response.statusText
  return new WeekError(response.status === 404 ? 'missing' : 'invalid', detail || `HTTP ${response.status}`)
}

/**
 * Add an item. The server re-plans and returns the viewed week. Other weeks may
 * have changed too (a deadline item can reach several), so the cache keeps only
 * the returned week. Throws WeekError with the server's message on a 422.
 */
export async function addItem(request: ItemRequest): Promise<Week> {
  const response = await fetch('/api/items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) throw await failure(response)
  const week: Week = await response.json()
  rememberOnly(week)
  return week
}

/** Forget every cached week except this one. */
function rememberOnly(week: Week): void {
  clearWeekCache()
  loaded.set(week.week_start, week)
  pending.set(week.week_start, Promise.resolve(week))
}

