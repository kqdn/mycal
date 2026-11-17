import { describe, expect, it } from 'vitest'
import {
  dayWords,
  emptyRuleForm,
  firstRuleError,
  pickerRows,
  ruleDetail,
  ruleFormFrom,
  ruleLabel,
  ruleSentence,
  ruleSummary,
  ruleTitle,
  sortRules,
  targetLine,
  targetWords,
  toRuleRequest,
  validateRule,
  type RuleForm,
  type RuleOut,
  type TargetOut,
} from './ruleForm'

const gym: TargetOut = { id: 's1', kind: 'series', title: 'Gym', week_start: null }
const reading: TargetOut = { id: 'i1', kind: 'item', title: 'Read for seminar', week_start: '2026-11-16' }
const lab: TargetOut = { id: 'i2', kind: 'item', title: 'Chemistry lab', week_start: '2026-11-16' }

const base = { source: null, max_min: null, weekdays: null, mode: null, ranges: null, min_gap_days: null, every_item: false, targets: [] }
const limit: RuleOut = { ...base, id: 'r1', kind: 'daily_limit', max_min: 120, weekdays: [5, 6], source: '2026-11-16.toml' }
const gymPref: RuleOut = {
  ...base,
  id: 'r2',
  kind: 'time_preference',
  mode: 'prefer',
  ranges: [
    { weekdays: [0, 1, 2, 3, 4], start_time: '16:00:00', end_time: '18:00:00' },
    { weekdays: [5, 6], start_time: '12:00:00', end_time: '14:00:00' },
  ],
  targets: [gym],
}
const rest: RuleOut = { ...base, id: 'r3', kind: 'rest_between', min_gap_days: 1, targets: [gym] }

describe('rule sentences', () => {
  it('reads like the DESIGN.md examples', () => {
    expect(ruleSentence(ruleFormFrom(limit))).toBe('At most 2h on weekends')
    expect(ruleSentence(ruleFormFrom(gymPref))).toBe('Gym: prefer 4:00 to 6:00pm on weekdays, 12:00 to 2:00pm on weekends')
    const avoid: RuleOut = {
      ...gymPref,
      mode: 'avoid',
      ranges: [{ weekdays: [0, 1, 2, 3, 4], start_time: '09:00:00', end_time: '12:00:00' }],
      targets: [reading],
    }
    expect(ruleSentence(ruleFormFrom(avoid))).toBe('Read for seminar: avoid 9:00am to 12:00pm on weekdays')
    expect(ruleSentence(ruleFormFrom(rest))).toBe('Gym: at least 1 day between sessions')
    expect(ruleSentence(ruleFormFrom({ ...rest, min_gap_days: 2, every_item: true, targets: [] }))).toBe(
      'Every item: at least 2 days between sessions',
    )
  })

  it('names days with words where they fit', () => {
    expect(dayWords([0, 1, 2, 3, 4])).toBe('on weekdays')
    expect(dayWords([5, 6])).toBe('on weekends')
    expect(dayWords([0, 1, 2, 3, 4, 5, 6])).toBe('every day')
    expect(dayWords([0, 2, 4])).toBe('on Mon, Wed, Fri')
    expect(dayWords([1, 2, 3])).toBe('on Tue to Thu')
  })

  it('lists one or two targets and shortens three or more', () => {
    expect(targetWords(false, [gym])).toBe('Gym')
    expect(targetWords(false, [gym, reading])).toBe('Gym, Read for seminar')
    expect(targetWords(false, [gym, reading, lab])).toBe('Gym and 2 more')
    expect(targetWords(true, [gym])).toBe('Every item')
  })

  it('leaves out what is not valid yet', () => {
    const form: RuleForm = { ...emptyRuleForm(), picked: [gym] }
    expect(ruleSummary(form)).toBe('The planner sees: Gym')
    expect(ruleSummary({ ...emptyRuleForm(), kind: 'daily_limit', limit: 'abc', limitDays: [] })).toBe('')
    expect(ruleSummary({ ...emptyRuleForm(), kind: 'rest_between' })).toBe('The planner sees: At least 1 day between sessions')
  })
})

describe('rule rows', () => {
  it('gives the kind, how strictly it is kept and the file', () => {
    expect(ruleDetail(limit)).toBe('Daily limit · Always kept · From 2026-11-16.toml')
    expect(ruleDetail(rest)).toBe('Rest days · A wish')
    expect(ruleLabel(rest)).toBe('Edit rule Gym: at least 1 day between sessions')
  })

  it('orders daily limits, then time preferences, then rest days', () => {
    expect(sortRules([rest, gymPref, limit]).map((r) => r.id)).toEqual(['r1', 'r2', 'r3'])
  })

  it('titles the dialog by kind when editing', () => {
    expect(ruleTitle(undefined)).toBe('New rule')
    expect(ruleTitle('rest_between')).toBe('Edit rest days')
    expect(ruleTitle('daily_limit')).toBe('Edit daily limit')
  })
})

describe('the rule dialog', () => {
  it('round-trips a stored rule into a request', () => {
    expect(toRuleRequest(ruleFormFrom(limit))).toEqual({
      kind: 'daily_limit',
      max_min: 120,
      weekdays: [5, 6],
      every_item: false,
      item_ids: [],
      series_ids: [],
    })
    expect(toRuleRequest(ruleFormFrom(gymPref))).toEqual({
      kind: 'time_preference',
      mode: 'prefer',
      ranges: [
        { weekdays: [0, 1, 2, 3, 4], start_time: '16:00', end_time: '18:00' },
        { weekdays: [5, 6], start_time: '12:00', end_time: '14:00' },
      ],
      every_item: false,
      item_ids: [],
      series_ids: ['s1'],
    })
  })

  it('sends no targets for every item or a daily limit', () => {
    const every = toRuleRequest({ ...ruleFormFrom(rest), everyItem: true })
    expect([every.every_item, every.item_ids, every.series_ids]).toEqual([true, [], []])
    const daily = toRuleRequest({ ...ruleFormFrom(limit), picked: [gym] })
    expect([daily.every_item, daily.series_ids]).toEqual([false, []])
  })

  it('checks each kind with the dialog messages', () => {
    const daily = { ...emptyRuleForm(), kind: 'daily_limit' as const }
    expect(validateRule({ ...daily, limit: 'soon' }).limit).toBe('Use a length like 2h or 1h 30m.')
    expect(validateRule({ ...daily, limit: '0m' }).limit).toBe('Use a length longer than 0m.')
    expect(validateRule({ ...daily, limit: '25h' }).limit).toBe('A day only has 24h.')
    expect(validateRule({ ...daily, limit: '2h', limitDays: [] })).toEqual({ limitDays: 'Pick at least one day.' })
    expect(validateRule({ ...daily, limit: '2h' })).toEqual({}) // no targets needed

    const rest = { ...emptyRuleForm(), kind: 'rest_between' as const, everyItem: true }
    expect(validateRule({ ...rest, gapDays: '7' }).gapDays).toBe('Use a whole number of days from 1 to 6.')
    expect(validateRule({ ...rest, gapDays: '1.5' }).gapDays).toBe('Use a whole number of days from 1 to 6.')
    expect(validateRule({ ...rest, everyItem: false }).targets).toBe('Pick at least one item, or choose Every item.')

    const pref = validateRule({
      ...emptyRuleForm(),
      picked: [gym],
      ranges: [
        { weekdays: [], startTime: '09:00', endTime: '10:00' },
        { weekdays: [0], startTime: '09:00', endTime: '09:00' },
      ],
    })
    expect(pref).toEqual({
      'range-0-days': 'Pick at least one day.',
      'range-1-times': "Start and end can't be the same time.",
    })
    expect(firstRuleError(pref)).toBe('range-0-days')
  })
})

describe('the target picker', () => {
  it('puts series first, then items, each alphabetical, and filters by title', () => {
    expect(pickerRows([reading, lab, gym], [], '').map((t) => t.title)).toEqual(['Gym', 'Chemistry lab', 'Read for seminar'])
    expect(pickerRows([reading, lab, gym], [], 'LAB').map((t) => t.title)).toEqual(['Chemistry lab'])
  })

  it("keeps a picked target the list doesn't have", () => {
    const old: TargetOut = { id: 'i9', kind: 'item', title: 'Old essay', week_start: '2026-11-02' }
    expect(pickerRows([gym], [old], '').map((t) => t.title)).toEqual(['Gym', 'Old essay'])
  })

  it('says what each target is', () => {
    expect(targetLine(gym)).toBe('Repeats')
    expect(targetLine(lab)).toBe('Nov 16 to 22')
  })
})
