// Rules (constraints) as pure logic: the Rule dialog's form, its validation,
// the request, and the one-sentence text a rule row and the dialog's summary
// line share. RuleDialog.tsx, TargetPicker.tsx and RulesPage.tsx only render
// this. See web/DESIGN.md, "Frames and rules".

import { clockMinutes, dayRange } from './frameForm'
import { parseDuration } from './itemForm'
import { estimateLabel, range12, weekTitle, type DateString } from './time'

export type RuleKind = 'daily_limit' | 'time_preference' | 'rest_between'
export type Mode = 'prefer' | 'avoid'

export const KINDS: { value: RuleKind; label: string; line: string; detail: string }[] = [
  { value: 'daily_limit', label: 'Daily limit', line: 'Always kept. Caps scheduled time on chosen days.', detail: 'Always kept' },
  { value: 'time_preference', label: 'Time preference', line: 'A wish. Prefer or avoid times of day.', detail: 'A wish' },
  { value: 'rest_between', label: 'Rest days', line: 'A wish. Leaves free days between sessions.', detail: 'A wish' },
]

export const MAX_RANGES = 6

/** GET /api/rules/targets: an item or series a rule can name. */
export interface TargetOut {
  id: string
  kind: 'item' | 'series'
  title: string
  week_start: DateString | null // a one-off item's week; null for a series
}

/** A time range as the API sends it. Times are "HH:MM:SS"; 0 = Monday. */
export interface RangeOut {
  weekdays: number[]
  start_time: string
  end_time: string
}

/** GET /api/rules: a rule in the dialog's terms. Only its kind's fields are set. */
export interface RuleOut {
  id: string
  kind: RuleKind
  source: string | null // the week file it came from, or null if added in the app
  max_min: number | null
  weekdays: number[] | null
  mode: Mode | null
  ranges: RangeOut[] | null
  min_gap_days: number | null
  every_item: boolean
  targets: TargetOut[]
}

/** The body of POST and PUT /api/rules. */
export interface RuleRequest {
  kind: RuleKind
  max_min?: number
  weekdays?: number[]
  mode?: Mode
  ranges?: RangeOut[]
  min_gap_days?: number
  every_item: boolean
  item_ids: string[]
  series_ids: string[]
}

export interface RangeForm {
  weekdays: number[]
  startTime: string // "HH:MM", as time inputs give them
  endTime: string
}

/** The dialog's fields as typed. Fields of other kinds stay, so changing kind keeps them. */
export interface RuleForm {
  kind: RuleKind
  limit: string // "2h", as in Estimate
  limitDays: number[]
  mode: Mode
  ranges: RangeForm[]
  gapDays: string
  everyItem: boolean
  picked: TargetOut[] // in the order picked
}

/** Field keys: fixed ones, plus "range-N-days" and "range-N-times" for each range. */
export type RuleErrors = Record<string, string>

const WEEKDAYS_MON_FRI = [0, 1, 2, 3, 4]

export function emptyRuleForm(): RuleForm {
  return {
    kind: 'time_preference',
    limit: '',
    limitDays: [...WEEKDAYS_MON_FRI],
    mode: 'prefer',
    ranges: [emptyRange()],
    gapDays: '1',
    everyItem: false,
    picked: [],
  }
}

export function emptyRange(): RangeForm {
  return { weekdays: [...WEEKDAYS_MON_FRI], startTime: '', endTime: '' }
}

export function ruleFormFrom(rule: RuleOut): RuleForm {
  const form = emptyRuleForm()
  form.kind = rule.kind
  form.everyItem = rule.every_item
  form.picked = [...rule.targets]
  if (rule.kind === 'daily_limit') {
    form.limit = rule.max_min === null ? '' : estimateLabel(rule.max_min)
    form.limitDays = [...(rule.weekdays ?? [])]
  } else if (rule.kind === 'time_preference') {
    form.mode = rule.mode ?? 'prefer'
    form.ranges = (rule.ranges ?? []).map((r) => ({
      weekdays: [...r.weekdays],
      startTime: r.start_time.slice(0, 5),
      endTime: r.end_time.slice(0, 5),
    }))
    if (form.ranges.length === 0) form.ranges = [emptyRange()]
  } else {
    form.gapDays = String(rule.min_gap_days ?? 1)
  }
  return form
}

const usesTargets = (kind: RuleKind) => kind !== 'daily_limit'

/** "0", "0m", "0h 0m": a length that reads fine but is zero. */
const isZero = (text: string) => /^\s*0+\s*(h\s*(0+\s*m)?|m)?\s*$/i.test(text)

/** The dialog's messages, as DESIGN.md words them. Keys follow the order of the fields. */
export function validateRule(form: RuleForm): RuleErrors {
  const errors: RuleErrors = {}
  if (form.kind === 'daily_limit') {
    const minutes = parseDuration(form.limit)
    if (isZero(form.limit)) errors.limit = 'Use a length longer than 0m.'
    else if (minutes === null) errors.limit = 'Use a length like 2h or 1h 30m.'
    else if (minutes > 24 * 60) errors.limit = 'A day only has 24h.'
    if (form.limitDays.length === 0) errors.limitDays = 'Pick at least one day.'
  }
  if (form.kind === 'time_preference') {
    form.ranges.forEach((range, i) => {
      if (range.weekdays.length === 0) errors[`range-${i}-days`] = 'Pick at least one day.'
      if (!range.startTime || !range.endTime) errors[`range-${i}-times`] = 'Pick a start and an end time.'
      else if (range.startTime === range.endTime) errors[`range-${i}-times`] = "Start and end can't be the same time."
    })
  }
  if (form.kind === 'rest_between' && !/^\s*[1-6]\s*$/.test(form.gapDays)) {
    errors.gapDays = 'Use a whole number of days from 1 to 6.'
  }
  if (usesTargets(form.kind) && !form.everyItem && form.picked.length === 0) {
    errors.targets = 'Pick at least one item, or choose Every item.'
  }
  return errors
}

export function firstRuleError(errors: RuleErrors): string | undefined {
  return Object.keys(errors)[0]
}

export function toRuleRequest(form: RuleForm): RuleRequest {
  const targets = usesTargets(form.kind) && !form.everyItem ? form.picked : []
  const request: RuleRequest = {
    kind: form.kind,
    every_item: usesTargets(form.kind) && form.everyItem,
    item_ids: targets.filter((t) => t.kind === 'item').map((t) => t.id),
    series_ids: targets.filter((t) => t.kind === 'series').map((t) => t.id),
  }
  if (form.kind === 'daily_limit') {
    request.max_min = parseDuration(form.limit) ?? 0
    request.weekdays = sortedDays(form.limitDays)
  } else if (form.kind === 'time_preference') {
    request.mode = form.mode
    request.ranges = form.ranges.map((r) => ({ weekdays: sortedDays(r.weekdays), start_time: r.startTime, end_time: r.endTime }))
  } else {
    request.min_gap_days = Number(form.gapDays.trim())
  }
  return request
}

const sortedDays = (days: number[]) => [...new Set(days)].sort((a, b) => a - b)

// The rule as one sentence (DESIGN.md, Rule rows and Summary lines)

/** Days in a rule sentence: "on weekdays", "on weekends", "every day", or "on Mon, Wed, Fri". */
export function dayWords(weekdays: number[]): string {
  const days = sortedDays(weekdays)
  if (days.length === 7) return 'every day'
  if (days.join() === '0,1,2,3,4') return 'on weekdays'
  if (days.join() === '5,6') return 'on weekends'
  return `on ${dayRange(days)}`
}

/** "Gym", "Gym, Read for seminar", "Gym and 2 more", or "Every item". */
export function targetWords(everyItem: boolean, targets: { title: string }[]): string {
  if (everyItem) return 'Every item'
  if (targets.length <= 2) return targets.map((t) => t.title).join(', ')
  return `${targets[0].title} and ${targets.length - 1} more`
}

/** A range in a sentence: "4:00 to 6:00pm on weekdays". */
function rangeWords(range: RangeForm): string {
  return `${range12(clockMinutes(range.startTime), clockMinutes(range.endTime))} ${dayWords(range.weekdays)}`
}

const rangeIsValid = (r: RangeForm) => r.weekdays.length > 0 && r.startTime !== '' && r.endTime !== '' && r.startTime !== r.endTime

/**
 * The rule as one sentence, the same text a row shows and the summary line
 * ends with. Parts that aren't valid yet are left out; '' if nothing is.
 *   "At most 2h on weekends"
 *   "Gym: prefer 4:00 to 6:00pm on weekdays, 12:00 to 2:00pm on weekends"
 *   "Gym: at least 1 day between sessions"
 */
export function ruleSentence(form: RuleForm): string {
  if (form.kind === 'daily_limit') {
    const minutes = parseDuration(form.limit)
    const length = minutes !== null && minutes <= 24 * 60 ? `At most ${estimateLabel(minutes)}` : ''
    const days = form.limitDays.length > 0 ? dayWords(form.limitDays) : ''
    return [length, days].filter(Boolean).join(' ')
  }
  let body = ''
  if (form.kind === 'time_preference') {
    const ranges = form.ranges.filter(rangeIsValid).map(rangeWords)
    body = ranges.length > 0 ? `${form.mode} ${ranges.join(', ')}` : ''
  } else if (/^\s*[1-6]\s*$/.test(form.gapDays)) {
    const n = Number(form.gapDays.trim())
    body = `at least ${n} ${n === 1 ? 'day' : 'days'} between sessions`
  }
  const who = targetWords(form.everyItem, form.picked)
  if (!body) return who
  if (!who) return body.charAt(0).toUpperCase() + body.slice(1)
  return `${who}: ${body}`
}

/** The dialog's summary line, or '' while nothing is valid. */
export function ruleSummary(form: RuleForm): string {
  const sentence = ruleSentence(form)
  return sentence ? `The planner sees: ${sentence}` : ''
}

/** A row's detail line: "Time preference · A wish · From 2026-11-16.toml". */
export function ruleDetail(rule: RuleOut): string {
  const kind = KINDS.find((k) => k.value === rule.kind)!
  return [kind.label, kind.detail, rule.source && `From ${rule.source}`].filter(Boolean).join(' · ')
}

/** The row's accessible name: "Edit rule Gym: at least 1 day between sessions". */
export function ruleLabel(rule: RuleOut): string {
  return `Edit rule ${ruleSentence(ruleFormFrom(rule))}`
}

/** The dialog title: "New rule", or "Edit daily limit" and the like. */
export function ruleTitle(editing: RuleKind | undefined): string {
  if (!editing) return 'New rule'
  return `Edit ${KINDS.find((k) => k.value === editing)!.label.toLowerCase()}`
}

// The target picker

/** A target's second line: "Repeats" for a series, else the item's week, "Nov 16 to 22". */
export function targetLine(target: TargetOut): string {
  if (target.kind === 'series') return 'Repeats'
  return target.week_start ? weekTitle(target.week_start) : ''
}

/**
 * The picker's rows: series first, then one-off items, each alphabetical, so
 * picked rows don't move. Targets the rule already names are kept even if the
 * list no longer has them. Filtered by title, case-insensitive.
 */
export function pickerRows(available: TargetOut[], picked: TargetOut[], filter: string): TargetOut[] {
  const byId = new Map(available.map((t) => [t.id, t]))
  for (const t of picked) if (!byId.has(t.id)) byId.set(t.id, t)
  const needle = filter.trim().toLowerCase()
  return [...byId.values()]
    .filter((t) => t.title.toLowerCase().includes(needle))
    .sort((a, b) => (a.kind === b.kind ? a.title.localeCompare(b.title) : a.kind === 'series' ? -1 : 1))
}

/** Rows in the page's order: daily limits, then time preferences, then rest days, each in the order added. */
export function sortRules(rules: RuleOut[]): RuleOut[] {
  const order = KINDS.map((k) => k.value)
  return [...rules].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind))
}
