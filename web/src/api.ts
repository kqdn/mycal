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
  unscheduled: { id: string; title: string }[]
}

export class WeekError extends Error {}

export async function fetchWeek(weekStart: DateString): Promise<Week> {
  const response = await fetch(`/api/weeks/${weekStart}`)
  if (response.ok) return response.json()
  if (response.status === 404) throw new WeekError(`No week file for ${weekStart}.`)
  const body = await response.json().catch(() => null)
  const detail = typeof body?.detail === 'string' ? body.detail : response.statusText
  throw new WeekError(`Could not load the week: ${detail || `HTTP ${response.status}`}`)
}
