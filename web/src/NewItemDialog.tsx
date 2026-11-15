import { useEffect, useRef, useState, type FormEvent } from 'react'
import { addItem, WeekError, type Week } from './api'
import {
  emptyForm,
  outsideWorkHours,
  PRESETS,
  showsEachDay,
  showsEstimate,
  showsOneSessionPerDay,
  summary,
  toRequest,
  validate,
  WEEKDAYS,
  type DayContext,
  type Errors,
  type Field,
  type ItemForm,
  type Preset,
} from './itemForm'
import { today, type DateString } from './time'

interface Props {
  weekStart: DateString
  timezone: string
  frames: DayContext['frames'] // the week's work-frame time, to tell which picked days are still open
  onClose: () => void
  onAdded: (week: Week) => void
}

/** The New item dialog (web/DESIGN.md, "Add item dialog"). Mounted while open. */
export function NewItemDialog({ weekStart, timezone, frames, onClose, onAdded }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleInput = useRef<HTMLInputElement>(null)
  const [form, setForm] = useState<ItemForm>(() => emptyForm(weekStart, today()))
  const [touched, setTouched] = useState<Set<Field>>(new Set())
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  // "Now" for the deadline and open-day checks, taken when the dialog opens. The server checks again on add.
  const [openedAt] = useState(() => new Date().toISOString())
  const context: DayContext = { now: openedAt, timezone, frames }

  // A native modal dialog keeps focus inside and makes Esc cancel.
  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    titleInput.current?.focus()
  }, [])

  const errors: Errors = validate(form, openedAt, timezone, { weekStart, frames })
  const valid = Object.keys(errors).length === 0
  const shown = (field: Field) => (touched.has(field) ? errors[field] : undefined)

  function update(changes: Partial<ItemForm>) {
    setForm((current) => ({ ...current, ...changes }))
  }

  function touch(field: Field) {
    setTouched((current) => new Set(current).add(field))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!valid || saving) return
    setSaving(true)
    setServerError(null)
    try {
      const week = await addItem(toRequest(form, weekStart))
      onAdded(week)
      dialog.current?.close()
    } catch (error) {
      setServerError(error instanceof WeekError ? error.message : "Can't reach the planner. Is uv run mycal-api running?")
      setSaving(false)
    }
  }

  return (
    <dialog
      ref={dialog}
      className="item-dialog"
      aria-labelledby="new-item-title"
      onClose={onClose}
      onCancel={(event) => saving && event.preventDefault()}
    >
      <form onSubmit={submit}>
        <header className="dialog-header">
          <button type="button" className="text-button" onClick={() => dialog.current?.close()} disabled={saving}>
            Cancel
          </button>
          <h2 id="new-item-title" className="dialog-title">
            New item
          </h2>
          <button type="submit" className="primary-button" disabled={!valid || saving}>
            {saving ? 'Adding...' : 'Add'}
          </button>
        </header>

        <fieldset className="dialog-body" disabled={saving}>
          {serverError && (
            <div className="banner" role="alert">
              <p className="banner-title">Couldn't add it</p>
              <p className="banner-body">{serverError}</p>
            </div>
          )}

          <div className="field">
            <label htmlFor="item-title" className="field-label">
              Title
            </label>
            <input
              id="item-title"
              ref={titleInput}
              className={shown('title') ? 'text-input invalid' : 'text-input'}
              value={form.title}
              onChange={(e) => update({ title: e.target.value })}
              onBlur={() => touch('title')}
              autoComplete="off"
            />
            <FieldError message={shown('title')} />
          </div>

          <div className="field">
            <span className="field-label" id="flexibility-label">
              Flexibility
            </span>
            <div className="choice-card" role="radiogroup" aria-labelledby="flexibility-label">
              {PRESETS.map(({ value, label }) => (
                <div key={value}>
                  <label className={form.preset === value ? 'choice-row selected' : 'choice-row'}>
                    <input
                      type="radio"
                      name="preset"
                      value={value}
                      checked={form.preset === value}
                      onChange={() => update({ preset: value as Preset })}
                      className="visually-hidden"
                    />
                    <span>{label}</span>
                    {form.preset === value && <Check />}
                  </label>
                  {form.preset === value && (
                    <PresetPanel form={form} weekStart={weekStart} context={context} update={update} touch={touch} shown={shown} />
                  )}
                </div>
              ))}
            </div>
          </div>

          {showsEstimate(form) && (
            <div className="field">
              <div className="field-pair">
                <div className="field">
                  <label htmlFor="item-estimate" className="field-label">
                    Estimate
                  </label>
                  <input
                    id="item-estimate"
                    className={shown('estimate') ? 'text-input invalid' : 'text-input'}
                    placeholder="1h 30m"
                    value={form.estimate}
                    onChange={(e) => update({ estimate: e.target.value })}
                    onBlur={() => touch('estimate')}
                    autoComplete="off"
                  />
                  <FieldError message={shown('estimate')} />
                </div>
                <div className="field">
                  <label htmlFor="item-longest" className="field-label">
                    Longest session
                  </label>
                  <input
                    id="item-longest"
                    className={shown('longestSession') ? 'text-input invalid' : 'text-input'}
                    placeholder="No limit"
                    value={form.longestSession}
                    onChange={(e) => update({ longestSession: e.target.value })}
                    onBlur={() => touch('longestSession')}
                    autoComplete="off"
                  />
                  <FieldError message={shown('longestSession')} />
                </div>
              </div>
              <p className="hint">Longer work is split into sessions up to this length.</p>
            </div>
          )}

          {showsEachDay(form) && (
            <div className="field">
              <label htmlFor="item-each-day" className="field-label">
                Each day
              </label>
              <input
                id="item-each-day"
                className={shown('eachDay') ? 'text-input invalid' : 'text-input'}
                placeholder="30m"
                value={form.eachDay}
                onChange={(e) => update({ eachDay: e.target.value })}
                onBlur={() => touch('eachDay')}
                autoComplete="off"
              />
              <FieldError message={shown('eachDay')} />
              <p className="hint">One session this long on every day you picked that hasn't passed.</p>
            </div>
          )}

          {showsOneSessionPerDay(form) && (
            <div className="switch-card">
              <div className="switch-text">
                <span className="row-title" id="one-per-day-label">
                  One session per day
                </span>
                <span className="row-sub">Puts each session on a different day.</span>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={form.oneSessionPerDay}
                aria-labelledby="one-per-day-label"
                className="switch"
                onClick={() => update({ oneSessionPerDay: !form.oneSessionPerDay })}
              >
                <span className="switch-track">
                  <span className="switch-knob" />
                </span>
              </button>
            </div>
          )}
        </fieldset>
      </form>
    </dialog>
  )
}

interface PanelProps {
  form: ItemForm
  weekStart: DateString
  context: DayContext
  update: (changes: Partial<ItemForm>) => void
  touch: (field: Field) => void
  shown: (field: Field) => string | undefined
}

/** The selected preset's fields, under its row. */
function PresetPanel({ form, weekStart, context, update, touch, shown }: PanelProps) {
  const line = summary(form, weekStart, context)
  const outside = outsideWorkHours(form, weekStart, context)
  const date = (
    <div className="field">
      <label htmlFor="item-day" className="field-label">
        Date
      </label>
      <input
        id="item-day"
        type="date"
        className={shown('day') ? 'text-input invalid' : 'text-input'}
        value={form.day}
        onChange={(e) => update({ day: e.target.value })}
        onBlur={() => touch('day')}
      />
      <FieldError message={shown('day')} />
    </div>
  )
  const times = (label: string, optional: boolean) => (
    <div className="field">
      <span className="field-label" id="item-times-label">
        {label}
        {optional && <span className="optional"> (optional)</span>}
      </span>
      <div className="time-pair" role="group" aria-labelledby="item-times-label">
        <input
          type="time"
          aria-label="Start time"
          className={shown('times') ? 'time-input invalid' : 'time-input'}
          value={form.startTime}
          onChange={(e) => update({ startTime: e.target.value })}
          onBlur={() => touch('times')}
        />
        <span className="time-to">to</span>
        <input
          type="time"
          aria-label="End time"
          className={shown('times') ? 'time-input invalid' : 'time-input'}
          value={form.endTime}
          onChange={(e) => update({ endTime: e.target.value })}
          onBlur={() => touch('times')}
        />
      </div>
      <FieldError message={shown('times')} />
      {outside && <p className="hint">Outside your work hours</p>}
    </div>
  )

  return (
    <div className="preset-panel">
      {(form.preset === 'exact' || form.preset === 'day' || form.preset === 'day_range') && date}
      {(form.preset === 'exact' || form.preset === 'day_range') && times('Time', false)}
      {(form.preset === 'days' || form.preset === 'every_day') && (
        <>
          <div className="field">
            <div className="weekday-picker" role="group" aria-label="Days">
              {WEEKDAYS.map((name, day) => {
                const on = form.weekdays.includes(day)
                return (
                  <button
                    key={name}
                    type="button"
                    aria-pressed={on}
                    className={on ? 'segment selected' : 'segment'}
                    onClick={() => {
                      update({ weekdays: on ? form.weekdays.filter((d) => d !== day) : [...form.weekdays, day] })
                      touch('weekdays')
                    }}
                  >
                    {name}
                  </button>
                )
              })}
            </div>
            <FieldError message={shown('weekdays')} />
          </div>
          {times('Only between', true)}
        </>
      )}
      {form.preset === 'before_deadline' && (
        <div className="field">
          <span className="field-label" id="item-due-label">
            Due
          </span>
          <div className="time-pair" role="group" aria-labelledby="item-due-label">
            <input
              type="date"
              aria-label="Due date"
              className={shown('due') ? 'time-input invalid' : 'time-input'}
              value={form.dueDate}
              onChange={(e) => update({ dueDate: e.target.value })}
              onBlur={() => touch('due')}
            />
            <input
              type="time"
              aria-label="Due time"
              className={shown('due') ? 'time-input invalid' : 'time-input'}
              value={form.dueTime}
              onChange={(e) => update({ dueTime: e.target.value })}
              onBlur={() => touch('due')}
            />
          </div>
          <FieldError message={shown('due')} />
        </div>
      )}
      {line && <p className="summary">{line}</p>}
    </div>
  )
}

function FieldError({ message }: { message?: string }) {
  return message ? <p className="field-error">{message}</p> : null
}

function Check() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="check">
      <path d="M4 9.5 7.5 13 14 5.5" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
