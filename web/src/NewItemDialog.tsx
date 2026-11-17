import { useEffect, useRef, useState, type FormEvent } from 'react'
import { addItem, addSeries, repeatItem, updateItem, updateSeries, WeekError, type Week } from './api'
import {
  emptyForm,
  firstError,
  outsideWorkHours,
  plannedHint,
  PRESETS,
  showsEachDay,
  showsEstimate,
  showsOneSessionPerDay,
  summary,
  toRequest,
  whenKey,
  WEEKDAYS,
  type DayContext,
  type Errors,
  type Field,
  type ItemForm,
  type Preset,
} from './itemForm'
import { fieldProps } from './fieldProps'
import {
  chooseRepeat,
  fitRepeat,
  perWeek,
  repeatChoices,
  repeats,
  repeatSummary,
  toSeriesRequest,
  validateWithRepeat,
} from './repeatForm'
import { Check, FieldError } from './fields'
import { today, type DateString } from './time'

interface Props {
  weekStart: DateString
  timezone: string
  frames: DayContext['frames'] // the week's work-frame time, to tell which picked days are still open
  slotMin: number // the planner's slot size, to show planned lengths
  // Set to edit an existing item or series: its id, where it came from, the form as stored, and its own week.
  // A series is edited with the Repeats field, and so is a one-off item (`repeatable`), which it can turn
  // into a series. An occurrence ("This one") is edited without it.
  editing?: {
    kind: 'item' | 'series'
    repeatable?: boolean
    id: string
    source: string | null
    form: ItemForm
    weekStart: DateString
  }
  onClose: () => void
  onSaved: (week: Week) => void
}

/**
 * The Add item dialog (web/DESIGN.md, "Add item dialog"), which also edits an item
 * ("Item details popover", Editing). Mounted while open.
 */
export function NewItemDialog({ weekStart, timezone, frames, slotMin, editing, onClose, onSaved }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleInput = useRef<HTMLInputElement>(null)
  // A days or every-day item belongs to its own week; the response shows the viewed one.
  const formWeek = editing?.weekStart ?? weekStart
  const [form, setForm] = useState<ItemForm>(() => editing?.form ?? emptyForm(weekStart, today()))
  const [touched, setTouched] = useState<Set<Field>>(new Set())
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const body = useRef<HTMLDivElement>(null)
  // Set when Add is pressed with errors (a new object each time); the effect goes there once it has rendered.
  const [goTo, setGoTo] = useState<{ field: Field } | null>(null)
  // "Now" for the deadline and open-day checks, taken when the dialog opens. The server checks again on add.
  const [openedAt] = useState(() => new Date().toISOString())
  const context: DayContext = { now: openedAt, timezone, frames, slotMin }

  // A native modal dialog keeps focus inside and makes Esc cancel.
  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    titleInput.current?.focus()
  }, [])

  // Editing without changing when the item is: a passed day or deadline is fine, as on the server.
  const unmoved = editing !== undefined && whenKey(form) === whenKey(editing.form)
  const editingSeries = editing?.kind === 'series'
  const showsRepeat = editing === undefined || editingSeries || editing.repeatable === true
  const errors: Errors = validateWithRepeat(
    form,
    openedAt,
    timezone,
    { weekStart: formWeek, frames, slotMin },
    unmoved,
    today(),
    editing !== undefined && form.startDate === editing.form.startDate, // its own start may have passed
  )
  const shown = (field: Field) => (touched.has(field) ? errors[field] : undefined)

  useEffect(() => {
    if (!goTo) return
    const element = dialog.current?.querySelector<HTMLElement>(`[data-field="${goTo.field}"]`)
    element?.focus({ preventScroll: true })
    element?.scrollIntoView({ block: 'center' })
  }, [goTo])

  // A server error shows in the banner at the top of the body, so bring it into view.
  useEffect(() => {
    if (serverError && body.current) body.current.scrollTop = 0
  }, [serverError])

  function update(changes: Partial<ItemForm>) {
    setForm((current) => ({ ...current, ...changes }))
  }

  function touch(field: Field) {
    setTouched((current) => new Set(current).add(field))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (saving) return
    const first = firstError(errors)
    if (first) {
      // Nothing is sent: show every error at its field and go to the first one.
      setTouched((current) => new Set([...current, ...(Object.keys(errors) as Field[])]))
      setGoTo({ field: first })
      return
    }
    setSaving(true)
    setServerError(null)
    try {
      let week: Week
      if (editingSeries) week = await updateSeries(editing.id, toSeriesRequest(form, formWeek), weekStart)
      else if (editing && repeats(form)) week = await repeatItem(editing.id, toSeriesRequest(form, formWeek), weekStart)
      else if (editing) week = await updateItem(editing.id, toRequest(form, formWeek), weekStart)
      else if (repeats(form)) week = await addSeries(toSeriesRequest(form, weekStart))
      else week = await addItem(toRequest(form, weekStart))
      onSaved(week)
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
            {editingSeries ? 'Edit repeating item' : editing ? 'Edit item' : 'New item'}
          </h2>
          <button type="submit" className="primary-button" disabled={saving}>
            {editing ? (saving ? 'Saving...' : 'Save') : saving ? 'Adding...' : 'Add'}
          </button>
        </header>

        {/* The div scrolls, since Chrome won't scroll a fieldset; the fieldset disables the form while saving. */}
        <div className="dialog-body" ref={body}>
          <fieldset className="dialog-fields" disabled={saving}>
            {editing?.source && (
              <p className="hint">From {editing.source}. Importing that file again with --replace undoes this edit.</p>
            )}
            {serverError && (
              <div className="banner" role="alert">
                <p className="banner-title">{editing ? "Couldn't save it" : "Couldn't add it"}</p>
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
                {...fieldProps('title', shown)}
                className={shown('title') ? 'text-input invalid' : 'text-input'}
                value={form.title}
                onChange={(e) => update({ title: e.target.value })}
                onBlur={() => touch('title')}
                autoComplete="off"
              />
              <FieldError field="title" message={shown('title')} />
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
                        onChange={() => setForm((current) => fitRepeat({ ...current, preset: value as Preset }))}
                        className="visually-hidden"
                      />
                      <span>{label}</span>
                      {form.preset === value && <Check />}
                    </label>
                    {form.preset === value && (
                      <PresetPanel
                        form={form}
                        weekStart={formWeek}
                        context={context}
                        update={update}
                        touch={touch}
                        shown={shown}
                        repeating={showsRepeat && repeats(form)}
                      />
                    )}
                  </div>
                ))}
              </div>
            </div>

            {showsRepeat && (
              <RepeatField form={form} editingSeries={editingSeries} update={update} touch={touch} shown={shown} />
            )}

            {showsEstimate(form) && (
              <div className="field">
                <div className="field-pair">
                  <div className="field">
                    <label htmlFor="item-estimate" className="field-label">
                      Estimate
                    </label>
                    <input
                      id="item-estimate"
                      {...fieldProps('estimate', shown)}
                      className={shown('estimate') ? 'text-input invalid' : 'text-input'}
                      placeholder="1h 30m"
                      value={form.estimate}
                      onChange={(e) => update({ estimate: e.target.value })}
                      onBlur={() => touch('estimate')}
                      autoComplete="off"
                    />
                    <FieldError field="estimate" message={shown('estimate')} />
                    <PlannedAs text={plannedHint(form.estimate, slotMin, 'up')} />
                  </div>
                  <div className="field">
                    <label htmlFor="item-longest" className="field-label">
                      Longest session
                    </label>
                    <input
                      id="item-longest"
                      {...fieldProps('longestSession', shown)}
                      className={shown('longestSession') ? 'text-input invalid' : 'text-input'}
                      placeholder="No limit"
                      value={form.longestSession}
                      onChange={(e) => update({ longestSession: e.target.value })}
                      onBlur={() => touch('longestSession')}
                      autoComplete="off"
                    />
                    <FieldError field="longestSession" message={shown('longestSession')} />
                    <PlannedAs text={plannedHint(form.longestSession, slotMin, 'down')} />
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
                  {...fieldProps('eachDay', shown)}
                  className={shown('eachDay') ? 'text-input invalid' : 'text-input'}
                  placeholder="30m"
                  value={form.eachDay}
                  onChange={(e) => update({ eachDay: e.target.value })}
                  onBlur={() => touch('eachDay')}
                  autoComplete="off"
                />
                <FieldError field="eachDay" message={shown('eachDay')} />
                <PlannedAs text={plannedHint(form.eachDay, slotMin, 'up')} />
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
        </div>
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
  repeating?: boolean // each occurrence's date fills in the date fields, so they are hidden
}

/** The selected preset's fields, under its row. */
function PresetPanel({ form, weekStart, context, update, touch, shown, repeating = false }: PanelProps) {
  const line = repeating ? repeatSummary(form) : summary(form, weekStart, context)
  const outside = outsideWorkHours(form, weekStart, context)
  const date = (
    <div className="field">
      <label htmlFor="item-day" className="field-label">
        Date
      </label>
      <input
        id="item-day"
        type="date"
        {...fieldProps('day', shown)}
        className={shown('day') ? 'text-input invalid' : 'text-input'}
        value={form.day}
        onChange={(e) => update({ day: e.target.value })}
        onBlur={() => touch('day')}
      />
      <FieldError field="day" message={shown('day')} />
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
          {...fieldProps('times', shown)}
          className={shown('times') ? 'time-input invalid' : 'time-input'}
          value={form.startTime}
          onChange={(e) => update({ startTime: e.target.value })}
          onBlur={() => touch('times')}
        />
        <span className="time-to">to</span>
        <input
          type="time"
          aria-label="End time"
          aria-invalid={shown('times') ? true : undefined}
          aria-describedby={shown('times') ? 'times-error' : undefined}
          className={shown('times') ? 'time-input invalid' : 'time-input'}
          value={form.endTime}
          onChange={(e) => update({ endTime: e.target.value })}
          onBlur={() => touch('times')}
        />
      </div>
      <FieldError field="times" message={shown('times')} />
      {outside && <p className="hint">Outside your work hours</p>}
    </div>
  )

  return (
    <div className="preset-panel">
      {!repeating && (form.preset === 'exact' || form.preset === 'day' || form.preset === 'day_range') && date}
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
                    data-field={day === 0 ? 'weekdays' : undefined}
                    aria-describedby={shown('weekdays') ? 'weekdays-error' : undefined}
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
            <FieldError field="weekdays" message={shown('weekdays')} />
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
            {!repeating && (
              <input
                type="date"
                aria-label="Due date"
                {...fieldProps('due', shown)}
                className={shown('due') ? 'time-input invalid' : 'time-input'}
                value={form.dueDate}
                onChange={(e) => update({ dueDate: e.target.value })}
                onBlur={() => touch('due')}
              />
            )}
            <input
              type="time"
              aria-label="Due time"
              data-field={repeating ? 'due' : undefined}
              aria-invalid={shown('due') ? true : undefined}
              aria-describedby={shown('due') ? 'due-error' : undefined}
              className={shown('due') ? 'time-input invalid' : 'time-input'}
              value={form.dueTime}
              onChange={(e) => update({ dueTime: e.target.value })}
              onBlur={() => touch('due')}
            />
          </div>
          <FieldError field="due" message={shown('due')} />
        </div>
      )}
      {line && <p className="summary">{line}</p>}
    </div>
  )
}

/** The length the planner will use, when it differs from what was typed. Never an error. */
function PlannedAs({ text }: { text?: string }) {
  return text ? <p className="hint">{text}</p> : null
}

interface RepeatProps {
  form: ItemForm
  editingSeries: boolean
  update: (changes: Partial<ItemForm>) => void
  touch: (field: Field) => void
  shown: (field: Field) => string | undefined
}

/** The Repeats field (web/DESIGN.md, "Repeat"): how often, on which days, and from when to when. */
function RepeatField({ form, editingSeries, update, touch, shown }: RepeatProps) {
  const choices = repeatChoices(form.preset, editingSeries)
  const unit = form.repeat === 'daily' ? 'days' : 'weeks'
  return (
    <div className="field">
      <span className="field-label" id="repeat-label">
        Repeats
      </span>
      <div className="segmented" role="radiogroup" aria-labelledby="repeat-label">
        {choices.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={form.repeat === value}
            className={form.repeat === value ? 'segment selected' : 'segment'}
            onClick={() => update(chooseRepeat(form, value))}
          >
            {label}
          </button>
        ))}
      </div>

      {repeats(form) && (
        <div className="repeat-panel">
          {form.repeat === 'weekly' && !perWeek(form.preset) && (
            <div className="field">
              <span className="field-label" id="repeat-days-label">
                On
              </span>
              <div className="weekday-picker" role="group" aria-labelledby="repeat-days-label">
                {WEEKDAYS.map((name, day) => {
                  const on = form.repeatDays.includes(day)
                  return (
                    <button
                      key={name}
                      type="button"
                      aria-pressed={on}
                      data-field={day === 0 ? 'repeatDays' : undefined}
                      aria-describedby={shown('repeatDays') ? 'repeatDays-error' : undefined}
                      className={on ? 'segment selected' : 'segment'}
                      onClick={() => {
                        update({ repeatDays: on ? form.repeatDays.filter((d) => d !== day) : [...form.repeatDays, day] })
                        touch('repeatDays')
                      }}
                    >
                      {name}
                    </button>
                  )
                })}
              </div>
              <FieldError field="repeatDays" message={shown('repeatDays')} />
            </div>
          )}

          <div className="field">
            <div className="interval-row">
              <label htmlFor="repeat-interval" className="time-to">
                Every
              </label>
              <input
                id="repeat-interval"
                inputMode="numeric"
                {...fieldProps('interval', shown)}
                className={shown('interval') ? 'time-input interval-input invalid' : 'time-input interval-input'}
                value={form.interval}
                onChange={(e) => update({ interval: e.target.value })}
                onBlur={() => touch('interval')}
                autoComplete="off"
              />
              <span className="time-to">{unit}</span>
            </div>
            <FieldError field="interval" message={shown('interval')} />
          </div>

          <div className="field-pair">
            <div className="field">
              <label htmlFor="repeat-start" className="field-label">
                Starts
              </label>
              <input
                id="repeat-start"
                type="date"
                {...fieldProps('startDate', shown)}
                className={shown('startDate') ? 'text-input invalid' : 'text-input'}
                value={form.startDate}
                onChange={(e) => update({ startDate: e.target.value })}
                onBlur={() => touch('startDate')}
              />
              <FieldError field="startDate" message={shown('startDate')} />
            </div>
            <div className="field">
              <label htmlFor="repeat-end" className="field-label">
                Ends <span className="optional">(optional)</span>
              </label>
              <input
                id="repeat-end"
                type="date"
                {...fieldProps('endDate', shown)}
                className={shown('endDate') ? 'text-input invalid' : 'text-input'}
                value={form.endDate}
                onChange={(e) => update({ endDate: e.target.value })}
                onBlur={() => touch('endDate')}
              />
              <FieldError field="endDate" message={shown('endDate')} />
            </div>
          </div>
          {perWeek(form.preset) && <p className="hint">Repeats as a whole week, starting on the Monday of its start date.</p>}
        </div>
      )}
    </div>
  )
}
