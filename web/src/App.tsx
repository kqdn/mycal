import { useEffect, useState } from 'react'
import { loadWeek, peekWeek, WeekError, type Week } from './api'
import { addDays, dayLabel, mondayOf, today, type DateString } from './time'
import { WeekGrid } from './WeekGrid'

type Result = { status: 'error'; message: string } | { status: 'ready'; week: Week }
type State = { status: 'loading' } | Result

/** The week in the URL (?week=2026-11-16), or this week's Monday. */
function weekFromUrl(): DateString {
  const param = new URLSearchParams(window.location.search).get('week')
  return param && /^\d{4}-\d{2}-\d{2}$/.test(param) ? mondayOf(param) : mondayOf(today())
}

export default function App() {
  const [weekStart, setWeekStart] = useState(weekFromUrl)
  // Each result remembers which week it is for; a newer week shows as loading.
  const [result, setResult] = useState<{ for: DateString } & Result>()
  // A week already in memory renders right away, with no loading step.
  const inMemory = peekWeek(weekStart)
  const state: State = inMemory
    ? { status: 'ready', week: inMemory }
    : result && result.for === weekStart
      ? result
      : { status: 'loading' }

  useEffect(() => {
    const onPop = () => setWeekStart(weekFromUrl())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    let current = true
    loadWeek(weekStart)
      .then((week) => {
        if (current) setResult({ for: weekStart, status: 'ready', week })
        // Warm the neighbors so the arrows are instant. A missing week is normal, so errors are ignored.
        for (const neighbor of [addDays(weekStart, -7), addDays(weekStart, 7)]) {
          loadWeek(neighbor).catch(() => {})
        }
      })
      .catch((error: unknown) => {
        const message =
          error instanceof WeekError ? error.message : 'Could not reach the API. Is `uv run mycal-api` running?'
        if (current) setResult({ for: weekStart, status: 'error', message })
      })
    return () => {
      current = false
    }
  }, [weekStart])

  function go(days: number) {
    const next = addDays(weekStart, days)
    window.history.pushState(null, '', `?week=${next}`)
    setWeekStart(next)
  }

  return (
    <main>
      <header>
        <button type="button" onClick={() => go(-7)} aria-label="Previous week">
          &larr;
        </button>
        <h1>Week of {dayLabel(weekStart)}</h1>
        <button type="button" onClick={() => go(7)} aria-label="Next week">
          &rarr;
        </button>
      </header>

      {state.status === 'loading' && <p className="note">Loading...</p>}
      {state.status === 'error' && <p className="note">{state.message}</p>}
      {state.status === 'ready' && !state.week.feasible && (
        <p className="note warn">
          No arrangement fits this week: some deadline, window or dependency can't be met.
        </p>
      )}
      {state.status === 'ready' && state.week.feasible && (
        <>
          <WeekGrid week={state.week} />
          {state.week.unscheduled.length > 0 && (
            <section className="unscheduled">
              <h2>Unscheduled</h2>
              <ul>
                {state.week.unscheduled.map((item) => (
                  <li key={item.id}>{item.title}</li>
                ))}
              </ul>
            </section>
          )}
          <p className="note small">Times in {state.week.timezone}</p>
        </>
      )}
    </main>
  )
}
