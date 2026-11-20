import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from 'react'
import type { Block, Week } from './api'
import { awaitsCheckIn, blockKind } from './checkIn'
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
}

/** What the compare view draws on the grid (web/DESIGN.md, "Compare view"). */
export interface Compare {
  tags: Map<string, { text: string; arrow: Arrow | null }> // by block id, for the changed blocks in the shown plan
  selected: string | null // block id
  other: { span: { start: string; end: string }; label: string } | null // the selected change's other spot
  onSelect: (blockId: string) => void
  reveal: number // bumped when a change tile is clicked: the grid scrolls to the selected change
}

export function WeekGrid({ week, onOpen, onAdd, focus, compare }: WeekGridProps) {
  const { week_start: weekStart, timezone, slot_min: slotMin } = week
  const scroller = useRef<HTMLDivElement>(null)
  const dates = weekDates(weekStart)
  const now = useNow(timezone)
  // The empty slot under the mouse, for the outline of what a click would add.
  const [hover, setHover] = useState<{ date: DateString; minutes: number } | null>(null)
  // A click that starts while a popover is open only closes it (the browser does that on release).
  const closingPopover = useRef(false)

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
                className={hover?.date === date ? 'day-column can-add' : 'day-column'}
                onMouseMove={(event) => {
                  const minutes = slotUnder(event, date)
                  setHover(minutes === null ? null : { date, minutes })
                }}
                onMouseLeave={() => setHover(null)}
                onPointerDown={() => {
                  closingPopover.current = document.querySelector(':popover-open') !== null
                }}
                onClick={(event) => {
                  const minutes = slotUnder(event, date)
                  if (minutes !== null && !closingPopover.current) onAdd?.(date, minutes, lengthAt(day, minutes))
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
                      onOpen={onOpen}
                      tag={compare?.tags.get(block.id) ?? null}
                      selected={compare?.selected === block.id}
                      onSelect={compare?.onSelect}
                    />
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
}

/**
 * A block is a button: clicking it, or Enter or Space, opens its details popover. A changed block
 * in the compare view selects its change instead, to show its other spot.
 */
function BlockView({ block, piece, timezone, now, onOpen, tag, selected, onSelect }: BlockViewProps) {
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
  let label = `${block.title}, ${weekdayShort(start.date)} ${range12(start.minutes, end.minutes)}`
  if (tag) label += `. ${tag.text}. Select to show the other spot.`
  const second = tag ? <ChangeTag text={tag.text} arrow={tag.arrow} /> : <span className="block-time">{range12(start.minutes, end.minutes)}</span>

  return (
    <button
      type="button"
      className={classes.join(' ')}
      style={style}
      aria-label={label}
      aria-haspopup={tag && onSelect ? undefined : 'dialog'}
      aria-pressed={tag && onSelect ? selected : undefined}
      data-block-id={block.id}
      onClick={(event) => (tag && onSelect ? onSelect(block.id) : onOpen(block, event.currentTarget))}
    >
      {mode === 'two-line' && (
        <>
          <span className="block-title">{block.title}</span>
          {second}
        </>
      )}
      {mode === 'one-line' && (
        <span className="block-title">
          {block.title} · {tag ? tag.text : time12(start.minutes)}
        </span>
      )}
      {mode === 'title-only' && <span className="block-title">{block.title}</span>}
    </button>
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
