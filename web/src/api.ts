// Types matching GET /api/weeks/{week_start} in solver/src/mycal/api.py.
// All times are UTC ISO strings.

import type { FrameOut, FrameRequest } from './frameForm'
import type { ItemRequest, OnMiss, Preset } from './itemForm'
import type { SeriesRequest } from './repeatForm'
import type { RuleOut, RuleRequest, TargetOut } from './ruleForm'
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
  series_id: string | null // set on an occurrence of a stored series
  occurrence_date?: DateString | null // an occurrence's date, so two of one series can be told apart
  due?: string | null // a "before a deadline" item's deadline (UTC ISO)
  // Check-ins (Milestone 7)
  checkable: boolean
  status: BlockStatus
  done_min: number | null // minutes done, for a done or partly done block
  missed_action: MissedAction | null // what ran on the missed part; null while an Ask waits
  history: boolean // the item has check-in history, so deleting it archives it
  on_miss: OnMiss // what a No does (an exact item's Reschedule comes as Skip)
  kept: number // the item's sessions that started, in every week: deleting it keeps them when it has history
  deleted: boolean // a kept session of a deleted item, shown as a record only
}

export type BlockStatus = 'planned' | 'done' | 'partial' | 'missed' | 'unanswered'
export type MissedAction = Exclude<OnMiss, 'ask'>

/** GET /api/check-ins: a block waiting for an answer, or for a choice about its missed part. */
export interface CheckIn {
  block_id: string
  item_id: string
  title: string
  start: string
  end: string
  fixed: boolean
  status: BlockStatus // planned when not answered yet
  done_min: number | null
  on_miss: OnMiss
  choices: MissedAction[]
}

/** POST /api/blocks/{id}/check-in */
export interface CheckInRequest {
  answer: 'yes' | 'partly' | 'no'
  done_min?: number
  action?: MissedAction
  accept_shortfall?: boolean
  catch_up?: ItemRequest // the catch-up item as changed in the item dialog
  propose?: boolean // hold it as a proposal to accept or discard (Milestone 8)
}

/**
 * POST /api/blocks/{id}/check-in/preview: what an answer would do to the missed time.
 * Nothing is saved. A catch-up comes as the item dialog's fields, with why it is due then.
 */
export interface CheckInPreview {
  action: MissedAction | null // null for Yes, or an Ask with no choice yet
  missed_min: number
  item_title: string
  catch_up: ItemFormOut | null
  due_reason: string | null // "next session", "Project 3 is due", "a week from now"
  recording: boolean // its estimate is the missed time × 1.25 (an exact-time item)
}

/** An "N times a week" item in the week that gets fewer sessions than it needs. */
export interface Shortfall {
  item_id: string
  title: string
  sessions: number
  gets: number
  message: string
}

/** How a series repeats. A days item repeats as a whole week: per_week, with no weekdays. */
export interface RepeatOut {
  id: string
  freq: 'daily' | 'weekly'
  interval: number
  weekdays: number[] // 0 = Monday
  per_week: boolean
  end_date: DateString | null
}

/** Work a proposal leaves over that wasn't left over before, across every week it re-planned. */
export interface LeftOver {
  item_id: string
  title: string
  minutes: number
  message: string // "1h won't fit before Fri 5pm"
}

/** The waiting proposal's version of the week (Milestone 8). */
export interface Proposal {
  summary: string // "Add Essay"
  blocks: Block[]
  unscheduled: Week['unscheduled']
  left_over: LeftOver[]
  overlaps: [string, string][] // block ids of fixed events that overlap (double booking)
  other_weeks: { week_start: DateString; changes: number }[] // other re-planned weeks whose blocks change
}

export interface Week {
  week_start: DateString
  timezone: string
  slot_min: number // the planner's slot size; lengths off it are rounded
  blocks: Block[]
  frames: { start: string; end: string }[]
  // `reason` is set when some of the item's work didn't fit, like "1h won't fit before Fri 5pm".
  unscheduled: {
    id: string
    title: string
    estimate_min: number | null
    reason: string | null
    sessions: number
    editable: boolean
    series_id: string | null
    history: boolean
    kept: number
  }[]
  series: RepeatOut[] // how each series with an occurrence in the week repeats
  shortfalls: Shortfall[] // not yet accepted
  proposal?: Proposal | null // set while a proposed change waits for Accept or Discard
  notice?: string | null // said once, like "the proposed change was dropped"
}

/** GET /api/series/{id}: a stored series in the dialog's terms. Times are "HH:MM:SS". */
export interface SeriesFormOut {
  id: string
  source: string | null
  title: string
  preset: Preset
  start_time: string | null
  end_time: string | null
  weekdays: number[] | null
  deadline_time: string | null
  estimate_min: number | null
  max_chunk_min: number | null
  one_block_per_day: boolean
  keep_length: boolean
  session_min: number | null
  checkable: boolean
  on_miss: OnMiss
  freq: 'daily' | 'weekly'
  interval: number
  repeat_weekdays: number[]
  start_date: DateString
  end_date: DateString | null
  skipped_dates?: DateString[] // from today on: dates whose occurrence was deleted
}

/** GET /api/items/{id}: a stored item in the dialog's terms. Lengths are as typed; times are "HH:MM:SS". */
export interface ItemFormOut {
  id: string
  source: string | null // the week file it was imported from, or null if added in the app
  editable: boolean
  series_id: string | null // set on an occurrence, which can't be made to repeat again
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
  keep_length: boolean
  session_min: number | null
  checkable: boolean
  on_miss: OnMiss
}

/** Why a request failed: not found (404), a question to confirm (409, like "fewer sessions"),
 * or anything else the API refused or could not do. */
export class WeekError extends Error {
  readonly kind: 'missing' | 'confirm' | 'invalid'

  constructor(kind: 'missing' | 'confirm' | 'invalid', message: string) {
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
  const kind = response.status === 404 ? 'missing' : response.status === 409 ? 'confirm' : 'invalid'
  return new WeekError(kind, detail || `HTTP ${response.status}`)
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
    body: JSON.stringify({ ...request, propose: true }),
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
    body: JSON.stringify({ ...request, propose: true }),
  })
  if (!response.ok) throw await failure(response)
  const returned: Week = await response.json()
  rememberOnly(returned)
  return returned
}

export async function deleteItem(itemId: string, week: DateString): Promise<Week> {
  const response = await fetch(`/api/items/${itemId}?week=${week}&propose=true`, { method: 'DELETE' })
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
  return sendForWeek(`/api/frames?week=${week}`, 'POST', proposed(request))
}

/** Change a work frame. A 404 (already gone) throws WeekError with kind 'missing'. */
export async function updateFrame(frameId: string, request: FrameRequest, week: DateString): Promise<Week> {
  return sendForWeek(`/api/frames/${frameId}?week=${week}`, 'PUT', proposed(request))
}

/** Delete a work frame. Refused with a 422 if a week would stop fitting without it. */
export async function deleteFrame(frameId: string, week: DateString): Promise<Week> {
  return sendForWeek(`/api/frames/${frameId}?week=${week}&propose=true`, 'DELETE')
}

// Rules (constraints). Like work frames, a change re-plans every week from this one on.

/** GET /api/rules: every rule in the dialog's terms. */
export async function listRules(): Promise<RuleOut[]> {
  const response = await fetch('/api/rules')
  if (!response.ok) throw await failure(response)
  return response.json()
}

/** GET /api/rules/targets: the items and series a rule can name. */
export async function listTargets(): Promise<TargetOut[]> {
  const response = await fetch('/api/rules/targets')
  if (!response.ok) throw await failure(response)
  return response.json()
}

/** Add a rule. Throws WeekError with the server's message on a 422. */
export async function addRule(request: RuleRequest, week: DateString): Promise<Week> {
  return sendForWeek(`/api/rules?week=${week}`, 'POST', proposed(request))
}

/** Change a rule (its kind stays). A 404 (already gone) throws WeekError with kind 'missing'. */
export async function updateRule(ruleId: string, request: RuleRequest, week: DateString): Promise<Week> {
  return sendForWeek(`/api/rules/${ruleId}?week=${week}`, 'PUT', proposed(request))
}

/** Delete a rule. Deleting a rule never makes a week stop fitting. */
export async function deleteRule(ruleId: string, week: DateString): Promise<Week> {
  return sendForWeek(`/api/rules/${ruleId}?week=${week}&propose=true`, 'DELETE')
}

/** A change's body, sent as a proposal: the server holds it until Accept or Discard (Milestone 8). */
function proposed<T extends object>(request: T): T & { propose: true } {
  return { ...request, propose: true }
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

// Series (repeating items). Adding or changing one re-plans every week from
// this one on, like a work frame, so the cache keeps only the returned week.

/** Add a repeating item. Throws WeekError with the server's message on a 422. */
export async function addSeries(request: SeriesRequest): Promise<Week> {
  return sendForWeek('/api/series', 'POST', proposed(request))
}

/** Turn a one-off item into a series; the item becomes its occurrence on the item's own date. */
export async function repeatItem(itemId: string, request: SeriesRequest, week: DateString): Promise<Week> {
  return sendForWeek(`/api/items/${itemId}/repeat?week=${week}`, 'POST', proposed(request))
}

/** A series as the edit dialog shows it. A 404 (already gone) throws WeekError with kind 'missing'. */
export async function getSeries(seriesId: string): Promise<SeriesFormOut> {
  const response = await fetch(`/api/series/${seriesId}`)
  if (!response.ok) throw await failure(response)
  return response.json()
}

/** Change a series: occurrences that haven't started are rebuilt, except ones edited by hand. */
export async function updateSeries(seriesId: string, request: SeriesRequest, week: DateString): Promise<Week> {
  return sendForWeek(`/api/series/${seriesId}?week=${week}`, 'PUT', proposed(request))
}

/** End a series: occurrences that haven't started go, past ones stay. */
export async function deleteSeries(seriesId: string, week: DateString): Promise<Week> {
  return sendForWeek(`/api/series/${seriesId}?week=${week}&propose=true`, 'DELETE')
}

// Check-ins (Milestone 7)

/** GET /api/check-ins: blocks waiting for an answer, earliest first. Also turns old ones into unanswered. */
export async function listCheckIns(): Promise<CheckIn[]> {
  const response = await fetch('/api/check-ins')
  if (!response.ok) throw await failure(response)
  return response.json()
}

/** Answer a check-in. A 422 says the missed time can't go anywhere; a 409 asks to accept fewer sessions. */
export async function answerCheckIn(blockId: string, request: CheckInRequest, week: DateString): Promise<Week> {
  return sendForWeek(`/api/blocks/${blockId}/check-in?week=${week}`, 'POST', request)
}

/** What an answer would do, without saving it. Throws WeekError with the server's sentence on a 422. */
export async function previewCheckIn(blockId: string, request: CheckInRequest): Promise<CheckInPreview> {
  const response = await fetch(`/api/blocks/${blockId}/check-in/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

/** Save the waiting proposal. A 404 means none waits any more (say, a check-in dropped it). */
export async function acceptProposal(week: DateString): Promise<Week> {
  return sendForWeek(`/api/proposal/accept?week=${week}`, 'POST')
}

/** Drop the waiting proposal, changing nothing. */
export async function discardProposal(week: DateString): Promise<Week> {
  return sendForWeek(`/api/proposal/discard?week=${week}`, 'POST')
}

/** Accept that an "N times a week" item gets fewer sessions, hiding its banner. */
export async function acceptShortfall(itemId: string, week: DateString): Promise<Week> {
  return sendForWeek(`/api/shortfalls/${itemId}/accept?week=${week}`, 'POST')
}
