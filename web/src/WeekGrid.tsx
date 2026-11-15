import { useLayoutEffect, useRef } from 'react'
import type { Week } from './api'
import { earliestMinute, pieces, weekDates } from './layout'
import { clock, dayLabel, toLocal } from './time'

const HOURS = Array.from({ length: 24 }, (_, h) => h)
const PX_PER_MIN = 1 // one hour is 60px tall

/** A read-only week: 7 local days, 24 hour rows, work frames shaded. */
export function WeekGrid({ week }: { week: Week }) {
  const { week_start: weekStart, timezone } = week
  const scroller = useRef<HTMLDivElement>(null)
  const dates = weekDates(weekStart)

  // Start scrolled to just above the earliest thing in the week.
  useLayoutEffect(() => {
    const first = earliestMinute(week.blocks, weekStart, timezone)
    if (scroller.current && first !== null) {
      scroller.current.scrollTop = Math.max(0, first - 30) * PX_PER_MIN
    }
  }, [week, weekStart, timezone])

  const frames = week.frames.flatMap((span) => pieces(span, weekStart, timezone))
  const blocks = week.blocks.flatMap((block) =>
    pieces(block, weekStart, timezone).map((piece) => ({ block, piece })),
  )

  return (
    <div className="grid">
      <div className="grid-head">
        <div className="gutter" />
        {dates.map((date) => (
          <div key={date} className="day-label">
            {dayLabel(date)}
          </div>
        ))}
      </div>
      <div className="grid-body" ref={scroller}>
        <div className="grid-canvas" style={{ height: 24 * 60 * PX_PER_MIN }}>
          <div className="gutter">
            {HOURS.map((h) => (
              <div key={h} className="hour-label" style={{ top: h * 60 * PX_PER_MIN }}>
                {clock(h * 60)}
              </div>
            ))}
          </div>
          {dates.map((date, day) => (
            <div key={date} className="day-column">
              {HOURS.map((h) => (
                <div key={h} className="hour-line" style={{ top: h * 60 * PX_PER_MIN }} />
              ))}
              {frames
                .filter((p) => p.day === day)
                .map((p) => (
                  <div
                    key={`frame-${p.startMin}`}
                    className="frame"
                    style={{ top: p.startMin * PX_PER_MIN, height: (p.endMin - p.startMin) * PX_PER_MIN }}
                  />
                ))}
              {blocks
                .filter(({ piece }) => piece.day === day)
                .map(({ block, piece }) => {
                  const start = toLocal(block.start, timezone)
                  const end = toLocal(block.end, timezone)
                  const classes = ['block', block.fixed ? 'fixed' : 'placed']
                  if (piece.continuesBefore) classes.push('cont-before')
                  if (piece.continuesAfter) classes.push('cont-after')
                  if (piece.endMin - piece.startMin < 30) classes.push('short') // title and time on one line
                  return (
                    <div
                      key={`${block.id}-${piece.day}`}
                      className={classes.join(' ')}
                      style={{ top: piece.startMin * PX_PER_MIN, height: (piece.endMin - piece.startMin) * PX_PER_MIN }}
                      title={`${block.title}, ${clock(start.minutes)}-${clock(end.minutes)}`}
                    >
                      <span className="block-title">{block.title}</span>
                      <span className="block-time">
                        {clock(start.minutes)}-{clock(end.minutes)}
                      </span>
                    </div>
                  )
                })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
