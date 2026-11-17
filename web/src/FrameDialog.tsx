import { useEffect, useRef, useState, type FormEvent } from 'react'
import { addFrame, deleteFrame, updateFrame, WeekError } from './api'
import { fieldProps } from './fieldProps'
import { FieldError } from './fields'
import {
  emptyFrameForm,
  firstFrameError,
  frameFormFrom,
  frameSummary,
  toFrameRequest,
  validateFrame,
  type FrameField,
  type FrameForm,
  type FrameOut,
} from './frameForm'
import { WEEKDAYS } from './itemForm'
import type { DateString } from './time'

interface Props {
  week: DateString // the week to return after a change (the one last viewed)
  editing?: FrameOut // set to edit or delete this frame
  onClose: () => void
  onSaved: () => void // saved: reload the list
  onDeleted: () => void // deleted (or already gone): reload the list
}

const CANT_REACH = "Can't reach the planner. Is uv run mycal-api running?"

/** The New frame and Edit frame dialog (web/DESIGN.md, "Frames and rules"). Mounted while open. */
export function FrameDialog({ week, editing, onClose, onSaved, onDeleted }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const nameInput = useRef<HTMLInputElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const cancelDelete = useRef<HTMLButtonElement>(null)
  const [form, setForm] = useState<FrameForm>(() => (editing ? frameFormFrom(editing) : emptyFrameForm()))
  const [touched, setTouched] = useState<Set<FrameField>>(new Set())
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const [goTo, setGoTo] = useState<{ field: FrameField } | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const busy = saving || deleting

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    nameInput.current?.focus()
  }, [])

  const errors = validateFrame(form)
  const shown = (field: FrameField) => (touched.has(field) ? errors[field] : undefined)

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

  function update(changes: Partial<FrameForm>) {
    setForm((current) => ({ ...current, ...changes }))
  }

  function touch(field: FrameField) {
    setTouched((current) => new Set(current).add(field))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    const first = firstFrameError(errors)
    if (first) {
      setTouched(new Set(Object.keys(errors) as FrameField[]))
      setGoTo({ field: first })
      return
    }
    setSaving(true)
    setServerError(null)
    try {
      const request = toFrameRequest(form)
      if (editing) await updateFrame(editing.id, request, week)
      else await addFrame(request, week)
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
      await deleteFrame(editing.id, week)
      onDeleted()
      dialog.current?.close()
    } catch (error) {
      if (error instanceof WeekError && error.kind === 'missing') {
        // Already gone: the list reloads without it.
        onDeleted()
        dialog.current?.close()
        return
      }
      setDeleteError(error instanceof WeekError ? error.message : CANT_REACH)
      setDeleting(false)
    }
  }

  const line = frameSummary(form)

  return (
    <dialog
      ref={dialog}
      className="item-dialog"
      aria-labelledby="frame-dialog-title"
      onClose={onClose}
      onCancel={(event) => busy && event.preventDefault()}
    >
      <form onSubmit={submit}>
        <header className="dialog-header">
          <button type="button" className="text-button" onClick={() => dialog.current?.close()} disabled={busy}>
            Cancel
          </button>
          <h2 id="frame-dialog-title" className="dialog-title">
            {editing ? 'Edit frame' : 'New frame'}
          </h2>
          <button type="submit" className="primary-button" disabled={busy}>
            {editing ? (saving ? 'Saving...' : 'Save') : saving ? 'Adding...' : 'Add'}
          </button>
        </header>

        <div className="dialog-body" ref={body}>
          <fieldset className="dialog-fields" disabled={busy}>
            {serverError && (
              <div className="banner" role="alert">
                <p className="banner-title">{editing ? "Couldn't save it" : "Couldn't add it"}</p>
                <p className="banner-body">{serverError}</p>
              </div>
            )}

            <div className="field">
              <label htmlFor="frame-name" className="field-label">
                Name
              </label>
              <input
                id="frame-name"
                ref={nameInput}
                {...fieldProps('name', shown)}
                className={shown('name') ? 'text-input invalid' : 'text-input'}
                placeholder="Weekdays"
                value={form.name}
                onChange={(e) => update({ name: e.target.value })}
                onBlur={() => touch('name')}
                autoComplete="off"
              />
              <FieldError field="name" message={shown('name')} />
            </div>

            <div className="field">
              <span className="field-label" id="frame-days-label">
                Days
              </span>
              <WeekdayPicker
                labelledBy="frame-days-label"
                value={form.weekdays}
                error={shown('weekdays')}
                onChange={(weekdays) => {
                  update({ weekdays })
                  touch('weekdays')
                }}
              />
              <FieldError field="weekdays" message={shown('weekdays')} />
            </div>

            <div className="field">
              <span className="field-label" id="frame-times-label">
                Time
              </span>
              <div className="time-pair" role="group" aria-labelledby="frame-times-label">
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
              <p className="hint">An end before the start ends the next day.</p>
            </div>

            {line && <p className="summary">{line}</p>}
          </fieldset>

          {editing && (
            <div className="dialog-delete">
              {!confirming ? (
                <button type="button" className="secondary-button danger" disabled={busy} onClick={() => setConfirming(true)}>
                  Delete frame
                </button>
              ) : (
                <div className="popover-confirm">
                  <div>
                    <p className="confirm-question">Delete this frame?</p>
                    <p className="confirm-detail">Items without their own times stop using it, every week.</p>
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

interface PickerProps {
  labelledBy: string
  value: number[]
  error?: string
  onChange: (weekdays: number[]) => void
}

/** Seven segmented day buttons, Mon to Sun. */
export function WeekdayPicker({ labelledBy, value, error, onChange }: PickerProps) {
  return (
    <div className="weekday-picker" role="group" aria-labelledby={labelledBy}>
      {WEEKDAYS.map((name, day) => {
        const on = value.includes(day)
        return (
          <button
            key={name}
            type="button"
            aria-pressed={on}
            data-field={day === 0 ? 'weekdays' : undefined}
            aria-describedby={error ? 'weekdays-error' : undefined}
            className={on ? 'segment selected' : 'segment'}
            onClick={() => onChange(on ? value.filter((d) => d !== day) : [...value, day])}
          >
            {name}
          </button>
        )
      })}
    </div>
  )
}
