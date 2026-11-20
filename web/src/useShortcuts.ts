import { useEffect, useRef } from 'react'
import { shortcutFor, type Action } from './shortcuts'

/**
 * Calls `handle` with each shortcut pressed on the page. `handle` returns true
 * when it acted, which stops the key's default (Backspace, an arrow's scroll).
 * Whether a dialog or the item popover is open is read from the page at the
 * moment of the key press, so no component has to pass that state around.
 */
export function useShortcuts(view: 'week' | 'rules', handle: (action: Action) => boolean): void {
  // The latest handler, so the listener is added once but always sees current state.
  const latest = useRef(handle)
  useEffect(() => {
    latest.current = handle
  })

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      const action = shortcutFor(event, {
        view,
        dialogOpen: document.querySelector('dialog[open]') !== null,
        popoverOpen: document.querySelector('.item-popover:popover-open') !== null,
        anyPopoverOpen: document.querySelector(':popover-open') !== null,
        onBlock: pointedBlock() !== null,
      })
      if (action && latest.current(action)) event.preventDefault()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [view])
}

/** The id of the shortcuts list (ShortcutsHelp), which ? and the top bar's button open. */
export const HELP_ID = 'shortcuts-help'

/** Open the shortcuts list, or close it if it's open. */
export function toggleHelp(): void {
  document.getElementById(HELP_ID)?.togglePopover()
}

/** The block button E and Delete act on: the one under the mouse, else the one with keyboard focus. */
export function pointedBlock(): HTMLElement | null {
  const hovered = document.querySelector<HTMLElement>('[data-block-id]:hover')
  if (hovered) return hovered
  const focused = document.activeElement
  return focused instanceof HTMLElement && focused.dataset.blockId ? focused : null
}
