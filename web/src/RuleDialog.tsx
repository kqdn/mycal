import { useEffect, useRef, useState, type FormEvent } from 'react'
import { addRule, deleteRule, listTargets, updateRule, WeekError } from './api'
import { Check, FieldError, WeekdayPicker } from './fields'
import { plannedHint } from './itemForm'
import {
  emptyRange,
  emptyRuleForm,
  firstRuleError,
  KINDS,
  MAX_RANGES,
  ruleFormFrom,
  ruleSummary,
  ruleTitle,
  toRuleRequest,
  validateRule,
  type RangeForm,
  type RuleForm,
  type RuleKind,
  type RuleOut,
  type TargetOut,
} from './ruleForm'
import { TargetPicker } from './TargetPicker'
import type { DateString } from './time'

interface Props {
  week: DateString // the week to return after a change (the one last viewed)
  slotMin: number | null // for "Planned as" under a daily limit; null if the week isn't loaded
  editing?: RuleOut
  onClose: () => void
  onSaved: () => void
  onDeleted: () => void
}

const CANT_REACH = "Can't reach the planner. Is uv run mycal-api running?"

/** The New rule and Edit rule dialog (web/DESIGN.md, "Frames and rules"). Mounted while open. */
export function RuleDialog({ week, slotMin, editing, onClose, onSaved, onDeleted }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const cancelDelete = useRef<HTMLButtonElement>(null)
  const [form, setForm] = useState<RuleForm>(() => (editing ? ruleFormFrom(editing) : emptyRuleForm()))
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const [goTo, setGoTo] = useState<{ field: string } | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [targets, setTargets] = useState<TargetOut[] | null>(null)
  const [targetsError, setTargetsError] = useState<string | null>(null)
  const busy = saving || deleting

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    // Adding: the selected kind. Editing: the first field.
    const first = editing
      ? element?.querySelector<HTMLElement>('.dialog-fields input:not([type="hidden"]), .dialog-fields button')
      : element?.querySelector<HTMLElement>('input[name="rule-kind"]:checked')
    first?.focus()
  }, [editing])

  useEffect(() => {
    let current = true
    listTargets()
      .then((rows) => current && setTargets(rows))
      .catch((error: unknown) => current && setTargetsError(error instanceof WeekError ? error.message : CANT_REACH))
    return () => {
      current = false
    }
  }, [])

  const errors = validateRule(form)
  const shown = (field: string) => (touched.has(field) ? errors[field] : undefined)

  useEffect(() => {
    if (!goTo) return
    const element = dialog.current?.querySelector<HTMLElement>(`[data-field="${goTo.field}"]`)
    element?.focus({ preventScroll: true })
    element?.scrollIntoView({ block: 'center' })
  }, [goTo])

  useEffect(() => {
    if (serverError && body.current) body.current.scrollTop = 0
  }, [serverError])

  useEffect(() => {
    if (confirming) cancelDelete.current?.focus()
  }, [confirming])

  function update(changes: Partial<RuleForm>) {
    setForm((current) => ({ ...current, ...changes }))
  }

  function updateRange(index: number, changes: Partial<RangeForm>) {
    setForm((current) => ({ ...current, ranges: current.ranges.map((r, i) => (i === index ? { ...r, ...changes } : r)) }))
  }

  function removeRange(index: number) {
    setForm((current) => ({ ...current, ranges: current.ranges.filter((_, i) => i !== index) }))
    // Range errors are keyed by position, so forget which ranges were touched.
    setTouched((current) => new Set([...current].filter((field) => !field.startsWith('range-'))))
  }

  function touch(field: string) {
    setTouched((current) => new Set(current).add(field))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    const first = firstRuleError(errors)
    if (first) {
      setTouched(new Set(Object.keys(errors)))
      setGoTo({ field: first })
      return
    }
    setSaving(true)
    setServerError(null)
    try {
      const request = toRuleRequest(form)
      if (editing) await updateRule(editing.id, request, week)
      else await addRule(request, week)
      onSaved()
      dialog.current?.close()
    } catch (error) {
      setServerError(error instanceof WeekError ? error.message : CANT_REACH)
      setSaving(false)
    }
  }

  async function remove() {
    if (!editing || busy) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteRule(editing.id, week)
      onDeleted()
      dialog.current?.close()
    } catch (error) {
      if (error instanceof WeekError && error.kind === 'missing') {
        onDeleted()
        dialog.current?.close()
        return
      }
      setDeleteError(error instanceof WeekError ? error.message : CANT_REACH)
      setDeleting(false)
    }
  }

  const line = ruleSummary(form)
  const limitHint = slotMin === null ? undefined : plannedHint(form.limit, slotMin, 'down')

  return (
    <dialog
      ref={dialog}
      className="item-dialog"
      aria-labelledby="rule-dialog-title"
      onClose={onClose}
      onCancel={(event) => busy && event.preventDefault()}
    >
      <form onSubmit={submit}>
        <header className="dialog-header">
          <button type="button" className="text-button" onClick={() => dialog.current?.close()} disabled={busy}>
            Cancel
          </button>
          <h2 id="rule-dialog-title" className="dialog-title">
            {ruleTitle(editing?.kind)}
          </h2>
          <button type="submit" className="primary-button" disabled={busy}>
            {editing ? (saving ? 'Saving...' : 'Save') : saving ? 'Adding...' : 'Add'}
          </button>
        </header>

        <div className="dialog-body" ref={body}>
          <fieldset className="dialog-fields" disabled={busy}>
            {editing?.source && (
              <p className="hint">From {editing.source}. Importing that file again with --replace undoes this edit.</p>
            )}
            {serverError && (
              <div className="banner" role="alert">
                <p className="banner-title">{editing ? "Couldn't save it" : "Couldn't add it"}</p>
                <p className="banner-body">{serverError}</p>
              </div>
            )}

            {!editing && (
              <div className="field">
                <span className="field-label" id="rule-kind-label">
                  Kind
                </span>
                <div className="choice-card" role="radiogroup" aria-labelledby="rule-kind-label">
                  {KINDS.map(({ value, label, line: kindLine }) => (
                    <div key={value}>
                      <label className={form.kind === value ? 'choice-row two-line selected' : 'choice-row two-line'}>
                        <input
                          type="radio"
                          name="rule-kind"
                          value={value}
                          checked={form.kind === value}
                          onChange={() => update({ kind: value as RuleKind })}
                          className="visually-hidden"
                        />
                        <span className="row-text">
                          <span className="kind-name">{label}</span>
                          <span className="row-sub">{kindLine}</span>
                        </span>
                        {form.kind === value && <Check />}
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {form.kind === 'daily_limit' && (
              <>
                <div className="field">
                  <label htmlFor="rule-limit" className="field-label">
                    At most
                  </label>
                  <input
                    id="rule-limit"
                    data-field="limit"
                    aria-invalid={shown('limit') ? true : undefined}
                    aria-describedby={shown('limit') ? 'limit-error' : undefined}
                    className={shown('limit') ? 'text-input invalid' : 'text-input'}
                    placeholder="2h"
                    value={form.limit}
                    onChange={(e) => update({ limit: e.target.value })}
                    onBlur={() => touch('limit')}
                    autoComplete="off"
                  />
                  <FieldError field="limit" message={shown('limit')} />
                  {limitHint && <p className="hint">{limitHint}</p>}
                </div>
                <div className="field">
                  <span className="field-label" id="limit-days-label">
                    On these days
                  </span>
                  <WeekdayPicker
                    labelledBy="limit-days-label"
                    field="limitDays"
                    value={form.limitDays}
                    error={shown('limitDays')}
                    onChange={(limitDays) => {
                      update({ limitDays })
                      touch('limitDays')
                    }}
                  />
                  <FieldError field="limitDays" message={shown('limitDays')} />
                  <p className="hint">Everything on those days counts, fixed events too.</p>
                </div>
              </>
            )}

            {form.kind === 'time_preference' && (
              <>
                <div className="field">
                  <span className="field-label" id="rule-mode-label">
                    Prefer or avoid
                  </span>
                  <div className="segmented-pair" role="group" aria-labelledby="rule-mode-label">
                    {(['prefer', 'avoid'] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        aria-pressed={form.mode === mode}
                        className={form.mode === mode ? 'segment selected' : 'segment'}
                        onClick={() => update({ mode })}
                      >
                        {mode === 'prefer' ? 'Prefer' : 'Avoid'}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="field">
                  <span className="field-label">Times</span>
                  <div className="range-cards">
                    {form.ranges.map((range, i) => (
                      <RangeCard
                        key={i}
                        index={i}
                        range={range}
                        removable={form.ranges.length > 1}
                        shown={shown}
                        touch={touch}
                        onChange={(changes) => updateRange(i, changes)}
                        onRemove={() => removeRange(i)}
                      />
                    ))}
                  </div>
                  {form.ranges.length < MAX_RANGES && (
                    <button
                      type="button"
                      className="add-range"
                      onClick={() => update({ ranges: [...form.ranges, emptyRange()] })}
                    >
                      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                        <path d="M9 3.5v11M3.5 9h11" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
                      </svg>
                      Add another range
                    </button>
                  )}
                  <p className="hint">
                    Prefer: work is placed in these times when it can. Avoid: kept out of them when it can. A wish, never a promise.
                  </p>
                </div>
              </>
            )}

            {form.kind === 'rest_between' && (
              <div className="field">
                <label htmlFor="rule-gap" className="field-label">
                  Free days between sessions
                </label>
                <input
                  id="rule-gap"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={6}
                  data-field="gapDays"
                  aria-invalid={shown('gapDays') ? true : undefined}
                  aria-describedby={shown('gapDays') ? 'gapDays-error' : undefined}
                  className={shown('gapDays') ? 'text-input number-input invalid' : 'text-input number-input'}
                  value={form.gapDays}
                  onChange={(e) => update({ gapDays: e.target.value })}
                  onBlur={() => touch('gapDays')}
                />
                <FieldError field="gapDays" message={shown('gapDays')} />
                <p className="hint">Same-day sessions count as too close. A wish: the planner breaks it before it misses a deadline.</p>
              </div>
            )}

            {form.kind !== 'daily_limit' && (
              <TargetPicker
                available={targets}
                loadError={targetsError}
                everyItem={form.everyItem}
                picked={form.picked}
                error={shown('targets')}
                onChange={(changes) => {
                  update(changes)
                  touch('targets')
                }}
              />
            )}

            {line && <p className="summary">{line}</p>}
          </fieldset>

          {editing && (
            <div className="dialog-delete">
              {!confirming ? (
                <button type="button" className="secondary-button danger" disabled={busy} onClick={() => setConfirming(true)}>
                  Delete rule
                </button>
              ) : (
                <div className="popover-confirm">
                  <div>
                    <p className="confirm-question">Delete this rule?</p>
                    <p className="confirm-detail">
                      {editing.source
                        ? `Importing ${editing.source} again with --replace brings it back.`
                        : 'The planner stops following it, every week.'}
                    </p>
                  </div>
                  <div className="popover-actions">
                    <button
                      ref={cancelDelete}
                      type="button"
                      className="secondary-button"
                      disabled={deleting}
                      onClick={() => {
                        setConfirming(false)
                        setDeleteError(null)
                      }}
                    >
                      Cancel
                    </button>
                    <button type="button" className="secondary-button danger" disabled={deleting} onClick={remove}>
                      {deleting ? 'Deleting...' : 'Delete'}
                    </button>
                  </div>
                  {deleteError && <p className="field-error">{deleteError}</p>}
                </div>
              )}
            </div>
          )}
        </div>
      </form>
    </dialog>
  )
}

interface RangeProps {
  index: number
  range: RangeForm
  removable: boolean
  shown: (field: string) => string | undefined
  touch: (field: string) => void
  onChange: (changes: Partial<RangeForm>) => void
  onRemove: () => void
}

/** One range of a time preference: days, then a start and an end time. */
function RangeCard({ index, range, removable, shown, touch, onChange, onRemove }: RangeProps) {
  const days = `range-${index}-days`
  const times = `range-${index}-times`
  const label = `range-${index}-label`
  return (
    <div className="range-card" role="group" aria-labelledby={removable ? label : undefined} aria-label={removable ? undefined : 'Range'}>
      {removable && (
        <div className="range-head">
          <span className="range-name" id={label}>
            Range {index + 1}
          </span>
          <button type="button" className="text-button range-remove" onClick={onRemove}>
            Remove
          </button>
        </div>
      )}
      <WeekdayPicker
        label={`Range ${index + 1} days`}
        field={days}
        value={range.weekdays}
        error={shown(days)}
        onChange={(weekdays) => {
          onChange({ weekdays })
          touch(days)
        }}
      />
      <FieldError field={days} message={shown(days)} />
      <div className="time-pair">
        <input
          type="time"
          aria-label={`Range ${index + 1} start time`}
          data-field={times}
          aria-invalid={shown(times) ? true : undefined}
          aria-describedby={shown(times) ? `${times}-error` : undefined}
          className={shown(times) ? 'time-input invalid' : 'time-input'}
          value={range.startTime}
          onChange={(e) => onChange({ startTime: e.target.value })}
          onBlur={() => touch(times)}
        />
        <span className="time-to">to</span>
        <input
          type="time"
          aria-label={`Range ${index + 1} end time`}
          aria-invalid={shown(times) ? true : undefined}
          aria-describedby={shown(times) ? `${times}-error` : undefined}
          className={shown(times) ? 'time-input invalid' : 'time-input'}
          value={range.endTime}
          onChange={(e) => onChange({ endTime: e.target.value })}
          onBlur={() => touch(times)}
        />
      </div>
      <FieldError field={times} message={shown(times)} />
    </div>
  )
}
