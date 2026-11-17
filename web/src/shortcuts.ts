// Keyboard shortcuts as pure logic: which action a key press means, given
// where you are. Components act on their own actions through useShortcuts.
// See web/DESIGN.md, "Keyboard shortcuts".

export type Action =
  | { type: 'tab'; view: 'week' | 'rules' }
  | { type: 'newItem' }
  | { type: 'moveWeek'; days: -7 | 7 }
  | { type: 'thisWeek' }
  | { type: 'newFrame' }
  | { type: 'newRule' }
  | { type: 'help' }
  | { type: 'edit' }
  | { type: 'delete' }

export interface KeyPress {
  key: string
  metaKey: boolean
  ctrlKey: boolean
  altKey: boolean
  target: EventTarget | null
}

export interface Where {
  view: 'week' | 'rules'
  dialogOpen: boolean // a modal dialog (adding or editing) is open
  popoverOpen: boolean // the item details popover is open
  onBlock: boolean // a block is under the mouse or has keyboard focus
}

/** The shortcuts as the help panel lists them, in order. */
export const SHORTCUTS: { keys: string[]; label: string; where: string }[] = [
  { keys: ['1'], label: 'Week', where: 'Anywhere' },
  { keys: ['2'], label: 'Frames and rules', where: 'Anywhere' },
  { keys: ['N'], label: 'New item', where: 'Week' },
  { keys: ['←', 'K'], label: 'Previous week', where: 'Week' },
  { keys: ['→', 'J'], label: 'Next week', where: 'Week' },
  { keys: ['T'], label: 'This week', where: 'Week' },
  { keys: ['E'], label: 'Edit the item', where: 'Pointing at a block, or its details' },
  { keys: ['Delete', 'D'], label: 'Delete the item (asks first)', where: 'Pointing at a block, or its details' },
  { keys: ['F'], label: 'New frame', where: 'Frames and rules' },
  { keys: ['R'], label: 'New rule', where: 'Frames and rules' },
  { keys: ['?'], label: 'These shortcuts', where: 'Anywhere' },
]

const TEXT_INPUTS = new Set(['text', 'search', 'email', 'number', 'password', 'tel', 'url', 'date', 'time', 'datetime-local', 'month', 'week'])

/** Whether the key press lands in a place you type into, where every key is just text. */
export function isTyping(target: EventTarget | null): boolean {
  if (!target || typeof (target as Element).tagName !== 'string') return false
  const element = target as HTMLElement
  const tag = element.tagName.toLowerCase()
  if (tag === 'textarea' || tag === 'select' || element.isContentEditable) return true
  return tag === 'input' && TEXT_INPUTS.has(((element as HTMLInputElement).type || 'text').toLowerCase())
}

/**
 * The action a key press means, or null to leave it alone. Nothing happens
 * while typing or while a dialog is open, and a key held with Cmd, Ctrl or
 * Alt is left to the browser. While the item popover is open, only its own
 * keys (E, Delete) and ? count, so arrows don't move the week out from under it.
 * Without the popover, E and Delete act on the block under the mouse or with focus.
 */
export function shortcutFor(press: KeyPress, where: Where): Action | null {
  if (press.metaKey || press.ctrlKey || press.altKey) return null
  if (where.dialogOpen || isTyping(press.target)) return null
  const key = press.key.length === 1 ? press.key.toLowerCase() : press.key

  if (key === '?') return { type: 'help' }
  if (where.popoverOpen) {
    if (key === 'e') return { type: 'edit' }
    if (key === 'Delete' || key === 'Backspace' || key === 'd') return { type: 'delete' }
    return null
  }
  if (where.view === 'week' && where.onBlock) {
    if (key === 'e') return { type: 'edit' }
    if (key === 'Delete' || key === 'Backspace' || key === 'd') return { type: 'delete' }
  }
  if (key === '1') return { type: 'tab', view: 'week' }
  if (key === '2') return { type: 'tab', view: 'rules' }

  if (where.view === 'week') {
    if (key === 'n') return { type: 'newItem' }
    if (key === 'ArrowLeft' || key === 'k') return { type: 'moveWeek', days: -7 }
    if (key === 'ArrowRight' || key === 'j') return { type: 'moveWeek', days: 7 }
    if (key === 't') return { type: 'thisWeek' }
  } else {
    if (key === 'f') return { type: 'newFrame' }
    if (key === 'r') return { type: 'newRule' }
  }
  return null
}
