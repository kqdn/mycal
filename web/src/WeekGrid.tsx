import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type PointerEvent as ReactPointerEvent } from 'react'
import type { Block, Week } from './api'
import { awaitsCheckIn, blockKind } from './checkIn'
import { canDrag, dropAt } from './drag'
import { clickedLength } from './itemForm'
import type { Arrow } from './proposal'
import { initialScrollMinute, minutesToPx, pieces, slotAt, slotHasBegun, textMode, weekDates, type Piece } from './layout'
import { hourLabel, range12, time12, toLocal, weekdayShort, type DateString } from './time'

const HOURS = Array.from({ length: 24 }, (_, h) => h)

/** A read-only week, styled per web/DESIGN.md: 7 local days, 24 hours, work frames as paper. */
interface WeekGridProps {
  week: Week
  onOpen: (block: Block, opener: HTMLElement) => void
  // A click on an empty slot that hasn't begun. Left out while a proposal waits, so empty slots do nothing.
  onAdd?: (date: DateString, minutes: number, lengthMin: number) => void
  // Where to scroll for what is being looked at, like a proposal's changes (key: which proposal). Scrolled to
  // once per key; flipping between the current plan and the proposal keeps the scroll.
  focus?: { key: string; minute: number } | null
  compare?: Compare | null // while a proposal waits: changed blocks' tags, the selected change and its other spot
  // A block was dragged to a free spot (UTC ISO start). Left out while a proposal waits, so nothing drags.
  // The grid keeps the dragged outline until the promise settles.
  onMove?: (block: Block, start: string) => Promise<void>
}

/** A block being dragged: where its top is (local date and minute) and how far down it was grabbed. */
interface Dragging {
  block: Block
  grabPx: number
  date: DateString
  minutes: number
  saving: boolean // dropped, and the move is being worked out
}

const DRAG_START_PX = 4 // a mouse or pen moves this far before a press becomes a drag, so a click still opens
const LONG_PRESS_MS = 400 // a finger holds this long first, so a swipe still scrolls
const EDGE_PX = 40 // dragging this close to the top or bottom of the grid scrolls it

/** What the compare view draws on the grid (web/DESIGN.md, "Compare view"). */
export interface Compare {
  tags: Map<string, { text: string; arrow: Arrow | null }> // by block id, for the changed blocks in the shown plan
  selected: string | null // block id
  other: { span: { start: string; end: string }; label: string } | null // the selected change's other spot
  onSelect: (blockId: string) => void
  reveal: number // bumped when a change tile is clicked: the grid scrolls to the selected change
}

export function WeekGrid({ week, onOpen, onAdd, focus, compare, onMove }: WeekGridProps) {
  const { week_start: weekStart, timezone, slot_min: slotMin } = week
  const scroller = useRef<HTMLDivElement>(null)
  const dates = weekDates(weekStart)
  const now = useNow(timezone)
  // The empty slot under the mouse, for the outline of what a click would add.
  const [hover, setHover] = useState<{ date: DateString; minutes: number } | null>(null)
  // A click that starts while a popover is open only closes it (the browser does that on release).
  const closingPopover = useRef(false)
  const columns = useRef<(HTMLDivElement | null)[]>([])
  const [drag, setDrag] = useState<Dragging | null>(null)
  const dragging = useRef(false) // a drag is under way: a finger doesn't scroll the page
  // The click the browser sends after a drop (on the block or the column under it) does nothing.
  const ignoreClicksUntil = useRef(0)
  const clickIgnored = () => performance.now() < ignoreClicksUntil.current

  useEffect(() => {
    const holdStill = (event: TouchEvent) => {
      if (dragging.current) event.preventDefault()
    }
    document.addEventListener('touchmove', holdStill, { passive: false })
    return () => document.removeEventListener('touchmove', holdStill)
  }, [])

  /** The local spot for a block's top with the pointer at (x, y), to the nearest slot, or null outside the days. */
  function spotAt(x: number, y: number, grabPx: number): { date: DateString; minutes: number } | null {
    for (const [day, column] of columns.current.entries()) {
      const rect = column?.getBoundingClientRect()
      if (rect && x >= rect.left && x < rect.right) {
        const minutes = slotAt(y - rect.top - grabPx + minutesToPx(slotMin) / 2, slotMin)
        return { date: dates[day], minutes }
      }
    }
    return null
  }

  /** Scroll the grid while the pointer is near its top or bottom edge. */
  function scrollNearEdge(y: number) {
    const body = scroller.current
    const head = body?.querySelector('.week-head')
    if (!body || !head) return
    if (y < head.getBoundingClientRect().bottom + EDGE_PX) body.scrollTop -= 16
    else if (y > body.getBoundingClientRect().bottom - EDGE_PX) body.scrollTop += 16
  }

  /**
   * A press on a block that can move. Mouse and pen drag once they move a few pixels; a finger
   * after a long press. Dropping on a free spot calls onMove; Escape or a refused spot snaps back.
   */
  function press(block: Block, event: ReactPointerEvent<HTMLButtonElement>) {
    if (!onMove || event.button !== 0 || drag?.saving || !canDrag(block, now.iso)) return
    const move = onMove
    const pointer = event.pointerId
    const origin = { x: event.clientX, y: event.clientY }
    const grabPx = event.clientY - event.currentTarget.getBoundingClientRect().top
    const touch = event.pointerType === 'touch'
    let active = false
    let last: Dragging | null = null

    const follow = (x: number, y: number) => {
      scrollNearEdge(y)
      const spot = spotAt(x, y, grabPx)
      if (spot) {
        last = { block, grabPx, ...spot, saving: false }
        setDrag(last)
      }
    }
    const begin = (x: number, y: number) => {
      active = true
      dragging.current = true
      follow(x, y)
    }
    const end = () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      window.removeEventListener('pointercancel', onCancel)
      window.removeEventListener('keydown', onKey)
      dragging.current = false
    }
    const onPointerMove = (e: PointerEvent) => {
      if (e.pointerId !== pointer) return
      const far = Math.hypot(e.clientX - origin.x, e.clientY - origin.y) > DRAG_START_PX
      if (active) follow(e.clientX, e.clientY)
      else if (far && touch) end() // a swipe before the long press: let it scroll
      else if (far) begin(e.clientX, e.clientY)
    }
    const onPointerUp = (e: PointerEvent) => {
      if (e.pointerId !== pointer) return
      end()
      if (!active) return
      ignoreClicksUntil.current = performance.now() + 400
      if (last) drop(last, move)
      else setDrag(null)
    }
    const onCancel = () => {
      end()
      setDrag(null)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || !active) return
      e.preventDefault()
      onCancel()
    }
    const timer = touch ? window.setTimeout(() => begin(origin.x, origin.y), LONG_PRESS_MS) : undefined
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    window.addEventListener('pointercancel', onCancel)
    window.addEventListener('keydown', onKey)
  }

  /** Move to the dropped spot, or snap back when it is refused or where the block already is. */
  function drop(at: Dragging, move: (block: Block, start: string) => Promise<void>) {
    const spot = dropAt(at.block, at.date, at.minutes, week.blocks, timezone, now.iso)
    if (spot.problem || Date.parse(spot.start) === Date.parse(at.block.start)) {
      setDrag(null)
      return
    }
    setDrag({ ...at, saving: true })
    move(at.block, spot.start).finally(() => setDrag(null))
  }

  const dropSpot = drag ? dropAt(drag.block, drag.date, drag.minutes, week.blocks, timezone, now.iso) : null
  const ghost = dropSpot ? pieces(dropSpot, weekStart, timezone) : []
  const ghostTime = dropSpot
    ? range12(toLocal(dropSpot.start, timezone).minutes, toLocal(dropSpot.end, timezone).minutes)
    : ''
  // A spot after the deadline is allowed, with a warning ("2:00 to 4:00am · After it's due").
  const ghostLabel = dropSpot?.problem ?? (dropSpot?.late ? `${ghostTime} · After it's due` : ghostTime)
  const ghostClass = dropSpot?.problem ? 'drag-ghost refused' : dropSpot?.late ? 'drag-ghost late' : 'drag-ghost'

  /** The slot under the pointer in a day column, or null over a block or a slot that has begun. */
  function slotUnder(event: MouseEvent<HTMLDivElement>, date: DateString): number | null {
    if (!onAdd || (event.target as HTMLElement).closest('.block')) return null
    const offset = event.clientY - event.currentTarget.getBoundingClientRect().top
    const minutes = slotAt(offset, slotMin)
    return slotHasBegun(date, minutes, now) ? null : minutes
  }

  /** How long a click at a slot makes its item: an hour, or up to the next block that day. */
  function lengthAt(day: number, minutes: number): number {
    const later = blocks.filter(({ piece }) => piece.day === day && piece.startMin > minutes).map(({ piece }) => piece.startMin)
    return clickedLength(minutes, later.length > 0 ? Math.min(...later) : null)
  }

  // Scroll when a week is first shown (to its focus, else its earliest block) and when a new focus comes.
  // Not when the same week is shown again, so toggling the compare view or saving keeps your place.
  const scrolledTo = useRef<{ week: DateString; focus: string | null } | null>(null)
  useLayoutEffect(() => {
    const last = scrolledTo.current
    const newWeek = last?.week !== weekStart
    const newFocus = focus != null && focus.key !== last?.focus
    if (scroller.current && (newWeek || newFocus)) {
      scroller.current.scrollTop = minutesToPx(focus ? focus.minute : initialScrollMinute(week))
    }
    scrolledTo.current = { week: weekStart, focus: focus?.key ?? null }
  }, [week, weekStart, focus])

  const frames = week.frames.flatMap((span) => pieces(span, weekStart, timezone))
  const blocks = week.blocks.flatMap((block) =>
    pieces(block, weekStart, timezone).map((piece) => ({ block, piece })),
  )
  const other = compare?.other ? pieces(compare.other.span, weekStart, timezone) : []

  // A change tile was clicked: bring its block into view, or its other spot when the shown plan has no
  // block for it (a block leaving the week, seen on the proposal). Up and down, and sideways on a narrow screen.
  const reveal = compare?.reveal ?? 0
  const revealing = compare?.selected ?? null
  useLayoutEffect(() => {
    if (reveal === 0 || revealing === null || !scroller.current) return
    const target =
      scroller.current.querySelector<HTMLElement>(`[data-block-id="${revealing}"]`) ??
      scroller.current.querySelector<HTMLElement>('.other-spot')
    target?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' })
  }, [reveal, revealing])

  return (
    <section className="week-card" aria-label="Week grid">
      {/* One scroll container for both directions. The day header is its sticky
          first row, so the header and the grid always share one width, scrollbar or not. */}
      <div className="week-body" ref={scroller} tabIndex={-1}>
        <div className="week-inner">
          <div className="week-head">
            <div className="gutter" />
            {dates.map((date) => {
              const isToday = date === now.date
              return (
                <div key={date} className={isToday ? 'day-head today' : 'day-head'}>
                  <span className="day-weekday">{weekdayShort(date)}</span>
                  <span className="day-date" aria-current={isToday ? 'date' : undefined}>
                    {Number(date.slice(8, 10))}
                  </span>
                </div>
              )
            })}
          </div>

          <div className="week-canvas" style={{ height: minutesToPx(24 * 60) }}>
            <div className="gutter">
              {HOURS.slice(1).map((h) => (
                <span key={h} className="hour-label" style={{ top: minutesToPx(h * 60) }}>
                  {hourLabel(h)}
                </span>
              ))}
            </div>
            {dates.map((date, day) => (
              <div
                key={date}
                ref={(element) => {
                  columns.current[day] = element
                }}
                className={hover?.date === date && !drag ? 'day-column can-add' : 'day-column'}
                onMouseMove={(event) => {
                  const minutes = drag ? null : slotUnder(event, date)
                  setHover(minutes === null ? null : { date, minutes })
                }}
                onMouseLeave={() => setHover(null)}
                onPointerDown={() => {
                  closingPopover.current = document.querySelector(':popover-open') !== null
                }}
                onClick={(event) => {
                  const minutes = slotUnder(event, date)
                  if (minutes !== null && !closingPopover.current && !clickIgnored()) {
                    onAdd?.(date, minutes, lengthAt(day, minutes))
                  }
                  closingPopover.current = false
                }}
              >
                {frames
                  .filter((p) => p.day === day)
                  .map((p) => (
                    <div key={`frame-${p.startMin}`} className="frame" style={place(p)} />
                  ))}
                {HOURS.slice(1).map((h) => (
                  <div key={h} className="hour-line" style={{ top: minutesToPx(h * 60) }} />
                ))}
                {blocks
                  .filter(({ piece }) => piece.day === day)
                  .map(({ block, piece }) => (
                    <BlockView
                      key={`${block.id}-${piece.day}`}
                      block={block}
                      piece={piece}
                      timezone={timezone}
                      now={now.iso}
                      onOpen={(b, opener) => !clickIgnored() && onOpen(b, opener)}
                      tag={compare?.tags.get(block.id) ?? null}
                      selected={compare?.selected === block.id}
                      onSelect={compare?.onSelect}
                      // A piece that began the day before has its top elsewhere, so it isn't grabbed.
                      draggable={!!onMove && !piece.continuesBefore && canDrag(block, now.iso)}
                      dragged={drag?.block.id === block.id}
                      onPress={press}
                    />
                  ))}
                {ghost
                  .filter((p) => p.day === day)
                  .map((p) => (
                    <div
                      key={`ghost-${p.startMin}`}
                      className={ghostClass}
                      style={place(p)}
                      aria-hidden="true"
                    >
                      {drag?.saving ? 'Moving...' : ghostLabel}
                    </div>
                  ))}
                {other
                  .filter((p) => p.day === day)
                  .map((p) => (
                    <div key={`other-${p.startMin}`} className="other-spot" style={place(p)} aria-hidden="true">
                      <span className="other-spot-label">{compare?.other?.label}</span>
                    </div>
                  ))}
                {hover?.date === date && <AddGhost minutes={hover.minutes} lengthMin={lengthAt(day, hover.minutes)} />}
                {date === now.date && (
                  <div className="now-line" style={{ top: minutesToPx(now.minutes) }} aria-hidden="true" />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="legend">
        <span className="legend-item">
          <span className="swatch fixed" aria-hidden="true" />
          Fixed
        </span>
        <span className="legend-item">
          <span className="swatch placed" aria-hidden="true" />
          Placed by the solver
        </span>
        {week.blocks.some((b) => b.locked) && (
          <span className="legend-item">
            <LockIcon />
            Placed by you
          </span>
        )}
        <span className="legend-item">
          <span className="swatch done" aria-hidden="true" />
          Done
        </span>
        <span className="legend-item">
          <span className="swatch missed" aria-hidden="true" />
          Missed
        </span>
        <span className="legend-item">
          <span className="swatch work-hours" aria-hidden="true" />
          Work hours
        </span>
        {compare && (
          <>
            <span className="legend-item">
              <span className="swatch changed" aria-hidden="true" />
              Changes in the new plan
            </span>
            <span className="legend-item">
              <span className="swatch other-spot-swatch" aria-hidden="true" />
              Other spot for the selected change
            </span>
          </>
        )}
      </div>
    </section>
  )
}

/** The outline of what a click would add. Short ones fit their time like a 15-minute block fits its title. */
function AddGhost({ minutes, lengthMin }: { minutes: number; lengthMin: number }) {
  const height = minutesToPx(lengthMin)
  return (
    <div
      className={`add-ghost ${textMode(height)}`}
      style={{ top: minutesToPx(minutes), height }}
      aria-hidden="true"
    >
      {time12(minutes)}
    </div>
  )
}

interface BlockViewProps {
  block: Block
  piece: Piece
  timezone: string
  now: string // UTC ISO, for whether the block is waiting for its check-in
  onOpen: (block: Block, opener: HTMLElement) => void
  tag: { text: string; arrow: Arrow | null } | null // a change in the compare view, shown in place of the time
  selected: boolean
  onSelect?: (blockId: string) => void
  draggable: boolean // it can be dragged to move it (Milestone 9)
  dragged: boolean // it is being dragged: drawn faint in its old spot
  onPress: (block: Block, event: ReactPointerEvent<HTMLButtonElement>) => void
}

/**
 * A block is a button: clicking it, or Enter or Space, opens its details popover. A changed block
 * in the compare view selects its change instead, to show its other spot.
 */
function BlockView({ block, piece, timezone, now, onOpen, tag, selected, onSelect, draggable, dragged, onPress }: BlockViewProps) {
  const start = toLocal(block.start, timezone)
  const end = toLocal(block.end, timezone)
  const style = place(piece)
  const mode = textMode(style.height)
  const classes = ['block', blockKind(block), mode]
  if (awaitsCheckIn(block, now)) classes.push('needs-check-in')
  if (piece.continuesBefore) classes.push('cont-before')
  if (piece.continuesAfter) classes.push('cont-after')
  if (tag) classes.push('changed')
  if (tag && selected) classes.push('selected')
  if (draggable) classes.push('draggable')
  if (dragged) classes.push('dragged')
  let label = `${block.title}, ${weekdayShort(start.date)} ${range12(start.minutes, end.minutes)}`
  if (block.locked) label += ', placed by you'
  if (tag) label += `. ${tag.text}. Select to show the other spot.`
  const second = tag ? <ChangeTag text={tag.text} arrow={tag.arrow} /> : <span className="block-time">{range12(start.minutes, end.minutes)}</span>
  const lock = block.locked ? <LockIcon /> : null

  return (
    <button
      type="button"
      className={classes.join(' ')}
      style={style}
      aria-label={label}
      aria-haspopup={tag && onSelect ? undefined : 'dialog'}
      aria-pressed={tag && onSelect ? selected : undefined}
      data-block-id={block.id}
      onPointerDown={draggable ? (event) => onPress(block, event) : undefined}
      onClick={(event) => (tag && onSelect ? onSelect(block.id) : onOpen(block, event.currentTarget))}
    >
      {mode === 'two-line' && (
        <>
          <span className="block-title">
            {lock}
            {block.title}
          </span>
          {second}
        </>
      )}
      {mode === 'one-line' && (
        <span className="block-title">
          {lock}
          {block.title} · {tag ? tag.text : time12(start.minutes)}
        </span>
      )}
      {mode === 'title-only' && (
        <span className="block-title">
          {lock}
          {block.title}
        </span>
      )}
    </button>
  )
}

/** A small padlock before the title of a block you placed by hand: the planner keeps it there. */
function LockIcon() {
  return (
    <svg className="block-lock" width="10" height="10" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  )
}

const ARROW_PATHS: Record<Arrow, string> = {
  up: 'M12 19V5M5 12l7-7 7 7',
  down: 'M12 5v14M19 12l-7 7-7-7',
  left: 'M19 12H5M12 5l-7 7 7 7',
  right: 'M5 12h14M12 5l7 7-7 7',
}

/** "From 6:00pm" with an arrow the way the block moved. */
function ChangeTag({ text, arrow }: { text: string; arrow: Arrow | null }) {
  return (
    <span className="change-tag">
      {arrow && (
        <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
          <path d={ARROW_PATHS[arrow]} />
        </svg>
      )}
      <span>{text}</span>
    </span>
  )
}

function place(piece: Piece): { top: number; height: number } {
  return { top: minutesToPx(piece.startMin), height: minutesToPx(piece.endMin - piece.startMin) }
}

/** The current local date and minute in the week's timezone, and the UTC ISO time, updated every minute. */
function useNow(timezone: string) {
  const at = (iso: string) => ({ ...toLocal(iso, timezone), iso })
  const [now, setNow] = useState(() => at(new Date().toISOString()))
  useEffect(() => {
    const tick = () => {
      const iso = new Date().toISOString()
      setNow({ ...toLocal(iso, timezone), iso })
    }
    const id = window.setInterval(tick, 60_000)
    return () => window.clearInterval(id)
  }, [timezone])
  return now
}
