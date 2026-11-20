import { describe, expect, it } from 'vitest'
import { isTyping, shortcutFor, SHORTCUTS, type KeyPress, type Where } from './shortcuts'

// Stand-ins for the element a key lands on: only tagName, type and isContentEditable are read.
const element = (tagName: string, extra: Record<string, unknown> = {}) =>
  ({ tagName, isContentEditable: false, ...extra }) as unknown as EventTarget
const BODY = element('BODY')
const BLOCK = element('BUTTON')

function press(key: string, changes: Partial<KeyPress> = {}): KeyPress {
  return { key, metaKey: false, ctrlKey: false, altKey: false, target: BODY, ...changes }
}

const WEEK: Where = { view: 'week', dialogOpen: false, popoverOpen: false, onBlock: false }
const RULES: Where = { view: 'rules', dialogOpen: false, popoverOpen: false, onBlock: false }
const POPOVER: Where = { ...WEEK, popoverOpen: true }

const on = (key: string, where: Where = WEEK, changes: Partial<KeyPress> = {}) => shortcutFor(press(key, changes), where)

describe('shortcutFor', () => {
  it('switches tabs with 1 and 2 from either page', () => {
    expect(on('1', RULES)).toEqual({ type: 'tab', view: 'week' })
    expect(on('2', WEEK)).toEqual({ type: 'tab', view: 'rules' })
  })

  it('moves between weeks with the arrows and with K and J', () => {
    expect([on('ArrowLeft'), on('k'), on('K')]).toEqual(Array(3).fill({ type: 'moveWeek', days: -7 }))
    expect([on('ArrowRight'), on('j')]).toEqual(Array(2).fill({ type: 'moveWeek', days: 7 }))
    expect(on('t')).toEqual({ type: 'thisWeek' })
  })

  it('switches between the current and new plan with S, on the week page only', () => {
    expect([on('s'), on('S')]).toEqual(Array(2).fill({ type: 'switchPlan' }))
    expect(on('s', RULES)).toBeNull()
    expect(on('s', POPOVER)).toBeNull()
    expect(on('s', WEEK, { target: element('INPUT', { type: 'text' }) })).toBeNull() // just text in a field
  })

  it('adds an item on the week page, and a frame or a rule on the Frames and rules page', () => {
    expect(on('n')).toEqual({ type: 'newItem' })
    expect(on('n', RULES)).toBeNull()
    expect(on('f', RULES)).toEqual({ type: 'newFrame' })
    expect(on('r', RULES)).toEqual({ type: 'newRule' })
    expect([on('f'), on('r')]).toEqual([null, null]) // never a surprise dialog on the week page
    expect(on('ArrowLeft', RULES)).toBeNull()
  })

  it('works when a block has focus, since blocks are buttons', () => {
    expect(on('j', WEEK, { target: BLOCK })).toEqual({ type: 'moveWeek', days: 7 })
  })

  it('gives the item popover only its own keys, and ?', () => {
    expect(on('e', POPOVER)).toEqual({ type: 'edit' })
    expect([on('Delete', POPOVER), on('Backspace', POPOVER), on('d', POPOVER)]).toEqual(Array(3).fill({ type: 'delete' }))
    expect([on('j', POPOVER), on('n', POPOVER), on('1', POPOVER)]).toEqual([null, null, null])
    expect(on('?', POPOVER)).toEqual({ type: 'help' })
    expect([on('e'), on('Delete'), on('d')]).toEqual([null, null, null]) // nothing to act on without a popover or a block
  })

  it('edits or deletes the block under the mouse or with focus, without opening it first', () => {
    const pointing = { ...WEEK, onBlock: true }
    expect(on('e', pointing)).toEqual({ type: 'edit' })
    expect([on('Delete', pointing), on('Backspace', pointing), on('D', pointing)]).toEqual(Array(3).fill({ type: 'delete' }))
    expect(on('j', pointing)).toEqual({ type: 'moveWeek', days: 7 }) // the other keys still work
    expect(on('e', { ...RULES, onBlock: true })).toBeNull()
  })

  it('leaves keys held with Cmd, Ctrl or Alt to the browser', () => {
    expect(on('t', WEEK, { metaKey: true })).toBeNull() // Cmd+T is a new tab
    expect(on('r', RULES, { ctrlKey: true })).toBeNull()
    expect(on('ArrowLeft', WEEK, { altKey: true })).toBeNull()
  })

  it('does nothing while a dialog is open or you are typing', () => {
    expect(on('n', { ...WEEK, dialogOpen: true })).toBeNull()
    expect(on('?', { ...WEEK, dialogOpen: true })).toBeNull()
    expect(on('n', WEEK, { target: element('INPUT', { type: 'text' }) })).toBeNull()
    expect(on('j', WEEK, { target: element('TEXTAREA') })).toBeNull()
  })

  it('ignores other keys', () => {
    expect([on('x'), on('Enter'), on(' '), on('Escape')]).toEqual([null, null, null, null])
  })
})

describe('isTyping', () => {
  it('counts text, date and time fields, text areas, selects and editable text', () => {
    for (const type of ['text', 'date', 'time', 'number', 'search']) expect(isTyping(element('INPUT', { type }))).toBe(true)
    expect(isTyping(element('INPUT', { type: '' }))).toBe(true) // no type means text
    expect(isTyping(element('TEXTAREA'))).toBe(true)
    expect(isTyping(element('SELECT'))).toBe(true)
    expect(isTyping(element('DIV', { isContentEditable: true }))).toBe(true)
  })

  it("doesn't count buttons, checkboxes or the page", () => {
    expect(isTyping(element('BUTTON'))).toBe(false)
    expect(isTyping(element('INPUT', { type: 'checkbox' }))).toBe(false)
    expect(isTyping(element('INPUT', { type: 'radio' }))).toBe(false)
    expect(isTyping(BODY)).toBe(false)
    expect(isTyping(null)).toBe(false)
  })
})

describe('SHORTCUTS', () => {
  it('lists every key shortcutFor knows', () => {
    const listed = SHORTCUTS.flatMap((s) => s.keys).map((k) => k.toLowerCase())
    expect(listed).toEqual(expect.arrayContaining(['1', '2', 'n', '←', 'k', '→', 'j', 't', 'e', 'delete', 'd', 'f', 'r', '?']))
  })
})
