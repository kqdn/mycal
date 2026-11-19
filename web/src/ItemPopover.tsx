import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Block, RepeatOut } from './api'
import { canCheckIn, checkInLine } from './checkIn'
import { confirmLine, keepLine, kindLine, popoverPosition, unscheduledLine, whenLine, type UnscheduledItem } from './itemDetails'
import { repeatLine } from './repeatForm'
import { pointedBlock, useShortcuts } from './useShortcuts'

/** The popover's bottom row: its actions, a delete's confirm step, or a series' "Edit which?" choice. */
export type Step = 'actions' | 'confirm' | 'pickEdit'

/** What the popover is about, the element that opened it (for placing it and returning focus),
 * and, from a keyboard shortcut, the step it opens on. */
export type PopoverTarget = (
  | { kind: 'block'; itemId: string; title: string; block: Block; opener: HTMLElement }
  | { kind: 'unscheduled'; itemId: string; title: string; item: UnscheduledItem; opener: HTMLElement }
) & { startAt?: Step }

/** Which an action on an occurrence of a series reaches: this date only, or the series. */
export type Scope = 'one' | 'series'

interface Props {
  target: PopoverTarget
  timezone: string
  repeat: RepeatOut | null // set when the item is an occurrence of a stored series
  deleting: boolean
  error: string | null
  opening: boolean // Edit is loading the item
  openError: string | null
  onEdit: (scope: Scope) => void
  onDelete: (scope: Scope) => void
  onCheckIn: (block: Block) => void
  onClose: () => void
}

/**
 * The item details popover (web/DESIGN.md, "Item details popover"). A native
 * popover="auto" element, so Escape and clicking outside close it at any time,
 * even while a delete runs. The delete itself lives in App, so it keeps going
 * after the popover closes. Mount it with a key per target so the confirm step
 * starts fresh.
 */
export function ItemPopover({ target, timezone, repeat, deleting, error, opening, openError, onEdit, onDelete, onCheckIn, onClose }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  // The actions row, or in its place: confirming a delete, or (for a series) picking what Edit changes.
  const [step, setStep] = useState<Step>(target.startAt ?? 'actions')
  const [chosen, setChosen] = useState<Scope>('one') // which delete is running, for its "Deleting..." label
  const confirming = step !== 'actions'
  const [openedAt] = useState(() => new Date().toISOString()) // "now" for "Already started"

  // Open, then place it next to what opened it. Again when the content changes size.
  useLayoutEffect(() => {
    const element = box.current
    if (!element) return
    if (!element.matches(':popover-open')) element.showPopover()
    const { left, top } = popoverPosition(
      target.opener.getBoundingClientRect(),
      { width: element.offsetWidth, height: element.offsetHeight },
      { width: window.innerWidth, height: window.innerHeight },
      target.kind === 'block' ? 'beside' : 'below',
    )
    element.style.left = `${left}px`
    element.style.top = `${top}px`
  }, [target, step, error, deleting, opening, openError])

  // When the browser closes it (Escape, a click outside), tell App and hand focus back.
  useEffect(() => {
    const element = box.current
    if (!element) return
    const onToggle = (event: Event) => {
      if ((event as Event & { newState?: string }).newState !== 'closed') return
      onClose()
      if (target.opener.isConnected) target.opener.focus()
    }
    element.addEventListener('toggle', onToggle)
    return () => element.removeEventListener('toggle', onToggle)
  }, [target, onClose])

  useEffect(() => {
    if (confirming) cancel.current?.focus()
  }, [confirming, step])

  const sessions = target.kind === 'block' ? target.block.sessions : target.item.sessions
  const editable = target.kind === 'block' ? target.block.editable : target.item.editable
  // Deleting an item with check-in history keeps its sessions that started (it is archived).
  const history = target.kind === 'block' ? target.block.history : target.item.history
  const kept = (target.kind === 'block' ? target.block.kept : target.item.kept) ?? 0
  // A kept session of a deleted item: a record only, with nothing to do.
  const deleted = target.kind === 'block' && target.block.deleted
  const checkInText = target.kind === 'block' ? checkInLine(target.block, openedAt) : ''
  const checkIn = target.kind === 'block' && !deleted && canCheckIn(target.block, openedAt) ? target.block : null

  // E and Delete do what the Edit and Delete item buttons do, from any step, so you can switch
  // between "Edit which?" and the delete confirm without starting over. Not while a delete or an
  // edit is loading. When the mouse is on another block, they're for that block, and App handles them.
  useShortcuts('week', (action) => {
    const pointed = pointedBlock()?.dataset.blockId
    if (pointed !== undefined && pointed !== (target.kind === 'block' ? target.block.id : undefined)) return false
    if (opening || deleting || deleted) return false
    if (action.type === 'edit' && editable) {
      if (repeat) setStep('pickEdit')
      else onEdit('one')
      return true
    }
    if (action.type === 'delete') {
      setStep('confirm')
      return true
    }
    return false
  })

  return (
    <div ref={box} popover="auto" className="item-popover" role="dialog" aria-label={target.title}>
      <p className="popover-title">{target.title}</p>
      {target.kind === 'block' && <p className="popover-when">{whenLine(target.block, timezone)}</p>}
      <p className="popover-kind">
        {target.kind === 'block' ? kindLine(target.block, openedAt) : unscheduledLine(target.item)}
      </p>

      {repeat && <p className="popover-kind">{repeatLine(repeat)}</p>}
      {checkInText && <p className="popover-check-in">{checkInText}</p>}

      {deleted && <p className="hint">Deleted. This session stays as a record.</p>}

      {step === 'actions' && !deleted && (
        <>
          {/* Check in gets its own full-width row; Edit and Delete share the row under it, half each. */}
          <div className="popover-buttons">
            {checkIn && (
              <button type="button" className="secondary-button popover-wide" disabled={opening} onClick={() => onCheckIn(checkIn)}>
                {checkIn.status === 'planned' ? 'Check in' : 'Change answer'}
              </button>
            )}
            <div className="popover-actions popover-halves">
              <button
                type="button"
                className="secondary-button"
                disabled={!editable || opening}
                onClick={() => (repeat ? setStep('pickEdit') : onEdit('one'))}
              >
                {opening ? 'Opening...' : 'Edit'}
              </button>
              <button type="button" className="secondary-button" disabled={opening} onClick={() => setStep('confirm')}>
                Delete item
              </button>
            </div>
          </div>
          {!editable && <p className="hint">Change Custom items in their week file.</p>}
          {openError && <p className="field-error">Couldn't open it: {openError}</p>}
        </>
      )}

      {step === 'pickEdit' && (
        <div className="popover-confirm">
          <div>
            <p className="confirm-question">Edit which?</p>
            <p className="confirm-detail">This changes only this date. All changes every date that hasn't started.</p>
          </div>
          <div className="popover-actions">
            <button ref={cancel} type="button" className="secondary-button" disabled={opening} onClick={() => setStep('actions')}>
              Cancel
            </button>
            <button type="button" className="secondary-button" disabled={opening} onClick={() => onEdit('one')}>
              This
            </button>
            <button type="button" className="secondary-button" disabled={opening} onClick={() => onEdit('series')}>
              {opening ? 'Opening...' : 'All'}
            </button>
          </div>
          {openError && <p className="field-error">Couldn't open it: {openError}</p>}
        </div>
      )}

      {step === 'confirm' && !repeat && (
        <div className="popover-confirm">
          <div>
            <p className="confirm-question">Delete this item?</p>
            <p className="confirm-detail">{history ? keepLine(sessions, kept) : confirmLine(sessions)}</p>
          </div>
          <div className="popover-actions">
            <button ref={cancel} type="button" className="secondary-button" disabled={deleting} onClick={() => setStep('actions')}>
              Cancel
            </button>
            <button type="button" className="secondary-button danger" disabled={deleting} onClick={() => onDelete('one')}>
              {deleting ? 'Deleting...' : 'Delete'}
            </button>
          </div>
          {error && <p className="field-error">Couldn't delete it: {error}</p>}
        </div>
      )}

      {step === 'confirm' && repeat && (
        <div className="popover-confirm">
          <div>
            <p className="confirm-question">Delete which?</p>
            <p className="confirm-detail">
              This skips only this date{history ? ', keeping its sessions that started on your calendar' : ''}. All stops it repeating:
              dates that haven't started go, and past ones stay.
            </p>
          </div>
          <div className="popover-actions">
            <button ref={cancel} type="button" className="secondary-button" disabled={deleting} onClick={() => setStep('actions')}>
              Cancel
            </button>
            {(['one', 'series'] as const).map((scope) => (
              <button
                key={scope}
                type="button"
                className="secondary-button danger"
                disabled={deleting}
                onClick={() => {
                  setChosen(scope)
                  onDelete(scope)
                }}
              >
                {deleting && chosen === scope ? 'Deleting...' : scope === 'one' ? 'This' : 'All'}
              </button>
            ))}
          </div>
          {error && <p className="field-error">Couldn't delete it: {error}</p>}
        </div>
      )}
    </div>
  )
}
