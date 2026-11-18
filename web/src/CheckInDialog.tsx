import { useEffect, useRef, useState, type FormEvent } from 'react'
import { answerCheckIn, WeekError, type Week } from './api'
import {
  ACTION_LABELS,
  ANSWERS,
  asksAction,
  checkInRequest,
  emptyCheckIn,
  lengthMin,
  validateCheckIn,
  type CheckInErrors,
  type CheckInForm,
  type CheckInTarget,
} from './checkIn'
import { FieldError } from './fields'
import { whenLine } from './itemDetails'
import { missHint } from './itemForm'
import { estimateLabel, type DateString } from './time'

interface Props {
  target: CheckInTarget
  timezone: string
  weekStart: DateString // the viewed week, which the answer returns
  onClose: () => void
  onSaved: (week: Week) => void
}

/**
 * The check-in dialog (web/DESIGN.md, "Check-ins"): Yes, Partly or No for one
 * session, and what happens to the time missed. Mounted while open.
 */
export function CheckInDialog({ target, timezone, weekStart, onClose, onSaved }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const [form, setForm] = useState<CheckInForm>(() => emptyCheckIn(target))
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  // A 409 asks to accept fewer sessions; the next Save sends that acceptance.
  const [question, setQuestion] = useState<string | null>(null)
  const errors: CheckInErrors = showErrors ? validateCheckIn(form, target) : {}
  const answered = target.status !== 'planned'

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    element?.querySelector<HTMLElement>('[role="radio"]')?.focus()
  }, [])

  useEffect(() => {
    if ((serverError || question) && body.current) body.current.scrollTop = 0
  }, [serverError, question])

  function update(changes: Partial<CheckInForm>) {
    setForm((current) => ({ ...current, ...changes }))
    setQuestion(null) // a different answer may not lose a session
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (saving) return
    if (Object.keys(validateCheckIn(form, target)).length > 0) {
      setShowErrors(true)
      return
    }
    setSaving(true)
    setServerError(null)
    try {
      const week = await answerCheckIn(target.block_id, checkInRequest(form, question !== null), weekStart)
      onSaved(week)
      dialog.current?.close()
    } catch (error) {
      if (error instanceof WeekError && error.kind === 'confirm') setQuestion(error.message)
      else setServerError(error instanceof WeekError ? error.message : "Can't reach the planner. Is uv run mycal-api running?")
      setSaving(false)
    }
  }

  const length = lengthMin(target)
  return (
    <dialog
      ref={dialog}
      className="item-dialog check-in-dialog"
      aria-labelledby="check-in-title"
      onClose={onClose}
      onCancel={(event) => saving && event.preventDefault()}
    >
      <form onSubmit={submit}>
        <header className="dialog-header">
          <button type="button" className="text-button" onClick={() => dialog.current?.close()} disabled={saving}>
            Cancel
          </button>
          <h2 id="check-in-title" className="dialog-title">
            {answered ? 'Change answer' : 'Check in'}
          </h2>
          <button type="submit" className="primary-button" disabled={saving}>
            {saving ? 'Saving...' : question ? 'Save anyway' : 'Save'}
          </button>
        </header>

        <div className="dialog-body" ref={body}>
          <fieldset className="dialog-fields" disabled={saving}>
            {question && (
              <div className="banner" role="alert">
                <p className="banner-title">Fewer sessions</p>
                <p className="banner-body">{question} Save anyway to accept it.</p>
              </div>
            )}
            {serverError && (
              <div className="banner" role="alert">
                <p className="banner-title">Couldn't save it</p>
                <p className="banner-body">{serverError}</p>
              </div>
            )}

            <div className="check-in-session">
              <span className="row-title">{target.title}</span>
              <span className="row-sub">
                {whenLine(target, timezone)} · {estimateLabel(length)}
              </span>
            </div>

            <div className="field">
              <span className="field-label" id="answer-label">
                Did you do it?
              </span>
              <div className="segmented" role="radiogroup" aria-labelledby="answer-label" data-field="answer">
                {ANSWERS.map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={form.answer === value}
                    className={form.answer === value ? 'segment selected' : 'segment'}
                    onClick={() => update({ answer: value })}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <FieldError field="answer" message={errors.answer} />
            </div>

            {form.answer === 'partly' && (
              <div className="field">
                <label htmlFor="check-in-done" className="field-label">
                  How much did you get done?
                </label>
                <input
                  id="check-in-done"
                  className={errors.done ? 'text-input invalid' : 'text-input'}
                  aria-invalid={errors.done ? true : undefined}
                  aria-describedby={errors.done ? 'done-error' : undefined}
                  placeholder="30m"
                  value={form.done}
                  onChange={(e) => update({ done: e.target.value })}
                  autoComplete="off"
                />
                <FieldError field="done" message={errors.done} />
                {!errors.done && <p className="hint">The rest counts as missed.</p>}
              </div>
            )}

            {asksAction(form) && (
              <div className="field">
                <span className="field-label" id="action-label">
                  {form.answer === 'partly' ? 'The rest' : 'The time you missed'}
                </span>
                <div className="segmented" role="radiogroup" aria-labelledby="action-label">
                  {target.choices.map((value) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={form.action === value}
                      className={form.action === value ? 'segment selected' : 'segment'}
                      onClick={() => update({ action: value })}
                    >
                      {ACTION_LABELS[value]}
                    </button>
                  ))}
                </div>
                <FieldError field="action" message={errors.action} />
                {form.action !== null && <p className="hint">{missHint(form.action)}</p>}
              </div>
            )}
          </fieldset>
        </div>
      </form>
    </dialog>
  )
}
