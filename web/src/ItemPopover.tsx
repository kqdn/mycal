import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Block } from './api'
import { confirmLine, kindLine, popoverPosition, unscheduledLine, whenLine, type UnscheduledItem } from './itemDetails'

/** What the popover is about, and the element that opened it (for placing it and returning focus). */
export type PopoverTarget =
  | { kind: 'block'; itemId: string; title: string; block: Block; opener: HTMLElement }
  | { kind: 'unscheduled'; itemId: string; title: string; item: UnscheduledItem; opener: HTMLElement }

interface Props {
  target: PopoverTarget
  timezone: string
  deleting: boolean
  error: string | null
  onDelete: () => void
  onClose: () => void
}

/**
 * The item details popover (web/DESIGN.md, "Item details popover"). A native
 * popover="auto" element, so Escape and clicking outside close it at any time,
 * even while a delete runs. The delete itself lives in App, so it keeps going
 * after the popover closes. Mount it with a key per target so the confirm step
 * starts fresh.
 */
export function ItemPopover({ target, timezone, deleting, error, onDelete, onClose }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const [confirming, setConfirming] = useState(false)
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
  }, [target, confirming, error, deleting])

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
  }, [confirming])

  const sessions = target.kind === 'block' ? target.block.sessions : target.item.sessions

  return (
    <div ref={box} popover="auto" className="item-popover" role="dialog" aria-label={target.title}>
      <p className="popover-title">{target.title}</p>
      {target.kind === 'block' && <p className="popover-when">{whenLine(target.block, timezone)}</p>}
      <p className="popover-kind">
        {target.kind === 'block' ? kindLine(target.block, openedAt) : unscheduledLine(target.item)}
      </p>

      {!confirming ? (
        <div className="popover-actions">
          <button type="button" className="secondary-button" onClick={() => setConfirming(true)}>
            Delete item
          </button>
        </div>
      ) : (
        <div className="popover-confirm">
          <div>
            <p className="confirm-question">Delete this item?</p>
            <p className="confirm-detail">{confirmLine(sessions)}</p>
          </div>
          <div className="popover-actions">
            <button ref={cancel} type="button" className="secondary-button" disabled={deleting} onClick={() => setConfirming(false)}>
              Cancel
            </button>
            <button type="button" className="secondary-button danger" disabled={deleting} onClick={onDelete}>
              {deleting ? 'Deleting...' : 'Delete'}
            </button>
          </div>
          {error && <p className="field-error">Couldn't delete it: {error}</p>}
        </div>
      )}
    </div>
  )
}
