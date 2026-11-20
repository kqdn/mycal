import { useEffect, useLayoutEffect, useRef } from 'react'
import { popoverPosition } from './itemDetails'

// Dropping a repeating fixed event (Milestone 9, web/DESIGN.md "Dragging a block"): move only this
// date, or this date and every later one. A native popover, styled like the item details popover;
// Escape and a press outside cancel it.

interface Props {
  title: string
  anchor: DOMRect // where it was dropped (the drag outline)
  onPick: (scope: 'one' | 'following') => void
  onCancel: () => void
}

export function MoveChoice({ title, anchor, onPick, onCancel }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const picked = useRef(false) // a pick closes it too; only a close without one cancels

  useLayoutEffect(() => {
    const element = box.current
    if (!element) return
    if (!element.matches(':popover-open')) element.showPopover()
    const { left, top } = popoverPosition(
      anchor,
      { width: element.offsetWidth, height: element.offsetHeight },
      { width: window.innerWidth, height: window.innerHeight },
      'beside',
    )
    element.style.left = `${left}px`
    element.style.top = `${top}px`
    cancel.current?.focus()
  }, [anchor])

  // A "manual" popover closes itself: the click a browser sends right after the drop lands outside
  // it, and an "auto" popover would take that as a click outside and close at once. Escape, or a
  // press outside after it opened, cancels.
  useEffect(() => {
    const element = box.current
    if (!element) return
    const onToggle = (event: Event) => {
      if ((event as Event & { newState?: string }).newState === 'closed' && !picked.current) onCancel()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      element.hidePopover()
    }
    const onPress = (event: PointerEvent) => {
      if (!element.contains(event.target as Node)) element.hidePopover()
    }
    element.addEventListener('toggle', onToggle)
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPress)
    return () => {
      element.removeEventListener('toggle', onToggle)
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPress)
    }
  }, [onCancel])

  function pick(scope: 'one' | 'following') {
    picked.current = true
    box.current?.hidePopover()
    onPick(scope)
  }

  return (
    <div ref={box} popover="manual" className="item-popover" role="dialog" aria-label={`Move ${title}`}>
      <p className="popover-title">{title}</p>
      <div className="popover-confirm">
        <div>
          <p className="confirm-question">Move which?</p>
          <p className="confirm-detail">This event only moves this date. This and following moves this date and every later one.</p>
        </div>
        <div className="popover-actions">
          <button ref={cancel} type="button" className="secondary-button" onClick={() => box.current?.hidePopover()}>
            Cancel
          </button>
          <button type="button" className="secondary-button" onClick={() => pick('one')}>
            This event only
          </button>
          <button type="button" className="secondary-button" onClick={() => pick('following')}>
            This and following
          </button>
        </div>
      </div>
    </div>
  )
}
