// Types matching GET /api/weeks/{week_start} in solver/src/mycal/api.py.
// All times are UTC ISO strings.

import type { FrameOut, FrameRequest } from './frameForm'
import type { ItemRequest, Preset } from './itemForm'
import type { DateString } from './time'

export interface Block {
  id: string
  item_id: string
  title: string
  start: string
  end: string
  fixed: boolean // an exact event, not work the solver placed
  // The item's sessions in every week, in start order: "Session 2 of 4".
  session: number
  sessions: number
  placed_min: number // the item's minutes placed so far, in every week
  estimate_min: number | null // null for an exact-time item
  editable: boolean // whether the edit dialog can change the item (not Custom)
}

export interface Week {
  week_start: DateString
  timezone: string
  slot_min: number // the planner's slot size; lengths off it are rounded
  feasible: boolean
  blocks: Block[]
  frames: { start: string; end: string }[]
  // `reason` is set when the item waits on a week that can't be planned.
  unscheduled: {
    id: string
    title: string
    estimate_min: number | null
    reason: string | null
    sessions: number
    editable: boolean
  }[]
}

/** GET /api/items/{id}: a stored item in the dialog's terms. Lengths are as typed; times are "HH:MM:SS". */
export interface ItemFormOut {
  id: string
  source: string | null // the week file it was imported from, or null if added in the app
  editable: boolean
  week_start: DateString // the item's own week for days and every-day items
  title: string
  preset: Preset | 'custom'
  day: DateString | null
  start_time: string | null
  end_time: string | null
  weekdays: number[] | null
  deadline_date: DateString | null
  deadline_time: string | null
  estimate_min: number | null
  max_chunk_min: number | null
  one_block_per_day: boolean
  session_min: number | null
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

/**
 * Delete an item. The server re-plans and returns `week`. Other weeks may have
 * changed too, so the cache keeps only the returned week. A 404 (already gone)
 * throws WeekError with kind 'missing'; other failures carry the server's message.
 */
/** An item as the edit dialog shows it. A 404 (already gone) throws WeekError with kind 'missing'. */
export async function getItem(itemId: string): Promise<ItemFormOut> {
  const response = await fetch(`/api/items/${itemId}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

/**
 * Change an item. The server re-plans and returns `week`; like adding, other
 * weeks may have changed, so the cache keeps only the returned week. Throws
 * WeekError with the server's message on a 422, and kind 'missing' on a 404.
 */
export async function updateItem(itemId: string, request: ItemRequest, week: DateString): Promise<Week> {
  const response = await fetch(`/api/items/${itemId}?week=${week}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) throw await failure(response)
  const returned: Week = await response.json()
  rememberOnly(returned)
  return returned
}

export async function deleteItem(itemId: string, week: DateString): Promise<Week> {
  const response = await fetch(`/api/items/${itemId}?week=${week}`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
  const returned: Week = await response.json()
  rememberOnly(returned)
  return returned
}

// Work frames. A change re-plans every week from this one on, so the cache
// keeps only the returned (viewed) week, as for items.

/** GET /api/frames: every work frame, by first weekday then start time. */
export async function listFrames(): Promise<FrameOut[]> {
  const response = await fetch('/api/frames')
  if (!response.ok) throw await failure(response)
  return response.json()
}

/** Add a work frame. Throws WeekError with the server's message on a 422 (a week would stop fitting). */
export async function addFrame(request: FrameRequest, week: DateString): Promise<Week> {
  return sendForWeek(`/api/frames?week=${week}`, 'POST', request)
}

/** Change a work frame. A 404 (already gone) throws WeekError with kind 'missing'. */
export async function updateFrame(frameId: string, request: FrameRequest, week: DateString): Promise<Week> {
  return sendForWeek(`/api/frames/${frameId}?week=${week}`, 'PUT', request)
}

/** Delete a work frame. Refused with a 422 if a week would stop fitting without it. */
export async function deleteFrame(frameId: string, week: DateString): Promise<Week> {
  return sendForWeek(`/api/frames/${frameId}?week=${week}`, 'DELETE')
}

/** Send a change that returns the viewed week, and keep only that week in the cache. */
async function sendForWeek(url: string, method: 'POST' | 'PUT' | 'DELETE', body?: unknown): Promise<Week> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw await failure(response)
  const returned: Week = await response.json()
  rememberOnly(returned)
  return returned
}
