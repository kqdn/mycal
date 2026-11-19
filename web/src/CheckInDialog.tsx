import { useEffect, useRef, useState, type FormEvent } from 'react'
import { answerCheckIn, previewCheckIn, WeekError, type CheckInPreview, type Week } from './api'
import {
  ACTION_LABELS,
  ANSWERS,
  answerHint,
  answerQuestion,
  asksAction,
  checkInRequest,
  emptyCheckIn,
  graceLine,
  lengthMin,
  missTile,
  previewRequest,
  validateCheckIn,
  type CheckInErrors,
  type CheckInForm,
  type CheckInTarget,
  type MissTile,
} from './checkIn'
import { FieldError } from './fields'
import { whenLine } from './itemDetails'
import { formFrom, missHint, type DayContext, type ItemRequest } from './itemForm'
import { NewItemDialog } from './NewItemDialog'
import { estimateLabel, today, type DateString } from './time'

interface Props {
  target: CheckInTarget
  timezone: string
  weekStart: DateString // the viewed week, which the answer returns
  frames: DayContext['frames'] // for the catch-up item dialog
  slotMin: number
  onClose: () => void
  onSaved: (week: Week) => void
}

/**
 * The check-in dialog (web/DESIGN.md, "Check-ins"): Yes, Partly or No for one
 * session, and what happens to the time missed. Mounted while open.
 */
export function CheckInDialog({ target, timezone, weekStart, frames, slotMin, onClose, onSaved }: Props) {
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
  const [openedAt] = useState(() => new Date().toISOString())
  // What the answer would do to the missed time, worked out by the server as the form changes.
  // Kept with the request it answers, so one for an earlier choice is never shown.
  const [previewed, setPreviewed] = useState<{ key: string; preview: CheckInPreview | null; error: string | null }>({
    key: '',
    preview: null,
    error: null,
  })
  const [editingCatchUp, setEditingCatchUp] = useState(false)
  const asked = previewRequest(form, target)
  const askedKey = asked === null ? '' : JSON.stringify(asked)
  const preview = previewed.key === askedKey ? previewed.preview : null
  const previewError = previewed.key === askedKey ? previewed.error : null

  useEffect(() => {
    if (askedKey === '') return
    let current = true
    // A short wait, so typing "1h 15m" asks once.
    const timer = window.setTimeout(() => {
      previewCheckIn(target.block_id, JSON.parse(askedKey))
        .then((shown) => {
          if (current) setPreviewed({ key: askedKey, preview: shown, error: null })
        })
        .catch((error: unknown) => {
          const message = error instanceof WeekError ? error.message : null
          if (current) setPreviewed({ key: askedKey, preview: null, error: message })
        })
    }, 250)
    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [askedKey, target.block_id])

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

  function saveCatchUp(request: ItemRequest): Promise<Week> {
    return answerCheckIn(target.block_id, { ...checkInRequest(form, question !== null), catch_up: request }, weekStart)
  }

  const length = lengthMin(target)
  const tile = preview === null ? null : missTile(preview, slotMin)
  const grace = graceLine(target, timezone, openedAt)
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
                {answerQuestion(target)}
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
              {!errors.answer && form.answer !== null && <p className="hint">{answerHint(form.answer)}</p>}
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
                {form.action !== null && tile === null && <p className="hint">{missHint(form.action)}</p>}
              </div>
            )}

            {asksAction(form) && tile && (
              <MissTileView tile={tile} onEdit={preview?.catch_up ? () => setEditingCatchUp(true) : undefined} />
            )}
            {asksAction(form) && previewError && <p className="field-error">{previewError}</p>}

            {grace && <p className="hint check-in-grace">{grace}</p>}
          </fieldset>
        </div>
      </form>

      {editingCatchUp && preview?.catch_up && (
        <NewItemDialog
          weekStart={weekStart}
          timezone={timezone}
          frames={frames}
          slotMin={slotMin}
          catchUp={{ form: formFrom(preview.catch_up, today()), weekStart: preview.catch_up.week_start, save: saveCatchUp }}
          onClose={() => setEditingCatchUp(false)}
          onSaved={(week) => {
            onSaved(week)
            dialog.current?.close()
          }}
        />
      )}
    </dialog>
  )
}

/** The tile under the choice (web/DESIGN.md, "Check-ins"): what happens to the missed time. A catch-up opens its item dialog. */
function MissTileView({ tile, onEdit }: { tile: MissTile; onEdit?: () => void }) {
  const body = (
    <>
      <span className="miss-tile-label">
        {tile.label}
        {onEdit && <span className="miss-tile-edit">Edit</span>}
      </span>
      <span className="miss-tile-title">{tile.title}</span>
      {tile.text && <span className="miss-tile-text">{tile.text}</span>}
      {tile.rows.map(([label, value]) => (
        <span key={label} className="miss-tile-row">
          <span className="miss-tile-key">{label}</span>
          <span>{value}</span>
        </span>
      ))}
    </>
  )
  return onEdit ? (
    <button type="button" className="miss-tile" onClick={onEdit} aria-label={`${tile.label}: ${tile.title}. Edit it`}>
      {body}
    </button>
  ) : (
    <div className="miss-tile">{body}</div>
  )
}
