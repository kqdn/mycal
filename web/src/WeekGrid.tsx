import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Block, Week } from './api'
import { awaitsCheckIn, blockKind } from './checkIn'
import { initialScrollMinute, minutesToPx, pieces, textMode, weekDates, type Piece } from './layout'
import { hourLabel, range12, time12, toLocal, weekdayShort } from './time'

const HOURS = Array.from({ length: 24 }, (_, h) => h)

/** A read-only week, styled per web/DESIGN.md: 7 local days, 24 hours, work frames as paper. */
export function WeekGrid({ week, onOpen }: { week: Week; onOpen: (block: Block, opener: HTMLElement) => void }) {
  const { week_start: weekStart, timezone } = week
  const scroller = useRef<HTMLDivElement>(null)
  const dates = weekDates(weekStart)
  const now = useNow(timezone)

  useLayoutEffect(() => {
    if (scroller.current) scroller.current.scrollTop = minutesToPx(initialScrollMinute(week))
  }, [week])

  const frames = week.frames.flatMap((span) => pieces(span, weekStart, timezone))
  const blocks = week.blocks.flatMap((block) =>
    pieces(block, weekStart, timezone).map((piece) => ({ block, piece })),
  )

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
              <div key={date} className="day-column">
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
                    />
                  ))}
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
      </div>
    </section>
  )
}

interface BlockViewProps {
  block: Block
  piece: Piece
  timezone: string
  now: string // UTC ISO, for whether the block is waiting for its check-in
  onOpen: (block: Block, opener: HTMLElement) => void
}

/** A block is a button: clicking it, or Enter or Space, opens its details popover. */
function BlockView({ block, piece, timezone, now, onOpen }: BlockViewProps) {
  const start = toLocal(block.start, timezone)
  const end = toLocal(block.end, timezone)
  const style = place(piece)
  const mode = textMode(style.height)
  const classes = ['block', blockKind(block), mode]
  if (awaitsCheckIn(block, now)) classes.push('needs-check-in')
  if (piece.continuesBefore) classes.push('cont-before')
  if (piece.continuesAfter) classes.push('cont-after')
  const label = `${block.title}, ${weekdayShort(start.date)} ${range12(start.minutes, end.minutes)}`

  return (
    <button
      type="button"
      className={classes.join(' ')}
      style={style}
      aria-label={label}
      aria-haspopup="dialog"
      data-block-id={block.id}
      onClick={(event) => onOpen(block, event.currentTarget)}
    >
      {mode === 'two-line' && (
        <>
          <span className="block-title">{block.title}</span>
          <span className="block-time">{range12(start.minutes, end.minutes)}</span>
        </>
      )}
      {mode === 'one-line' && (
        <span className="block-title">
          {block.title} · {time12(start.minutes)}
        </span>
      )}
      {mode === 'title-only' && <span className="block-title">{block.title}</span>}
    </button>
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
