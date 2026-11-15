import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Block, Week } from './api'
import { initialScrollMinute, minutesToPx, pieces, textMode, weekDates, type Piece } from './layout'
import { hourLabel, range12, time12, toLocal, weekdayShort } from './time'

const HOURS = Array.from({ length: 24 }, (_, h) => h)

/** A read-only week, styled per web/DESIGN.md: 7 local days, 24 hours, work frames as paper. */
export function WeekGrid({ week }: { week: Week }) {
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
      <div className="week-hscroll">
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

          <div className="week-body" ref={scroller}>
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
                      <BlockView key={`${block.id}-${piece.day}`} block={block} piece={piece} timezone={timezone} />
                    ))}
                  {date === now.date && (
                    <div className="now-line" style={{ top: minutesToPx(now.minutes) }} aria-hidden="true" />
                  )}
                </div>
              ))}
            </div>
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
          <span className="swatch work-hours" aria-hidden="true" />
          Work hours
        </span>
      </div>
    </section>
  )
}

function BlockView({ block, piece, timezone }: { block: Block; piece: Piece; timezone: string }) {
  const start = toLocal(block.start, timezone)
  const end = toLocal(block.end, timezone)
  const style = place(piece)
  const mode = textMode(style.height)
  const classes = ['block', block.fixed ? 'fixed' : 'placed', mode]
  if (piece.continuesBefore) classes.push('cont-before')
  if (piece.continuesAfter) classes.push('cont-after')
  const label = `${block.title}, ${weekdayShort(start.date)} ${range12(start.minutes, end.minutes)}`

  return (
    <div className={classes.join(' ')} style={style} role="group" aria-label={label}>
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
    </div>
  )
}

function place(piece: Piece): { top: number; height: number } {
  return { top: minutesToPx(piece.startMin), height: minutesToPx(piece.endMin - piece.startMin) }
}

/** The current local date and minute in the week's timezone, updated every minute. */
function useNow(timezone: string) {
  const [now, setNow] = useState(() => toLocal(new Date().toISOString(), timezone))
  useEffect(() => {
    const tick = () => setNow(toLocal(new Date().toISOString(), timezone))
    const id = window.setInterval(tick, 60_000)
    return () => window.clearInterval(id)
  }, [timezone])
  return now
}
