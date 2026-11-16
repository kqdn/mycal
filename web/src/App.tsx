import { useCallback, useEffect, useRef, useState } from 'react'
import { clearWeekCache, deleteItem, loadWeek, peekWeek, WeekError, type Week } from './api'
import { weekAfterDelete } from './itemDetails'
import { ItemPopover, type PopoverTarget } from './ItemPopover'
import { NewItemDialog } from './NewItemDialog'
import { addDays, estimateLabel, mondayOf, today, weekTitle, type DateString } from './time'
import { WeekGrid } from './WeekGrid'

type Problem = { title: string; body: string }
type Result = { status: 'error'; problem: Problem } | { status: 'ready'; week: Week }
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
  const [adding, setAdding] = useState(false)
  const [reload, setReload] = useState(0) // bump to fetch the viewed week again
  // The item details popover, and deletes started from it. A delete keeps
  // running after the popover closes, so its state lives here.
  const [open, setOpen] = useState<PopoverTarget | null>(null)
  const [pending, setPending] = useState<Set<string>>(new Set())
  const [deleteErrors, setDeleteErrors] = useState<Record<string, string>>({})
  const [pageProblem, setPageProblem] = useState<Problem | null>(null)
  // What a finishing delete needs to know now, not when it started.
  const viewing = useRef(weekStart)
  const openItem = useRef<string | null>(null)
  useEffect(() => {
    viewing.current = weekStart
  }, [weekStart])
  useEffect(() => {
    openItem.current = open?.itemId ?? null
  }, [open])
  const closePopover = useCallback(() => setOpen(null), [])
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
        if (current) setResult({ for: weekStart, status: 'error', problem: describe(error, weekStart) })
      })
    return () => {
      current = false
    }
  }, [weekStart, reload])

  async function remove(target: PopoverTarget) {
    const { itemId, title } = target
    setPending((ids) => new Set(ids).add(itemId))
    setDeleteErrors((errors) => {
      const rest = { ...errors }
      delete rest[itemId]
      return rest
    })
    try {
      const week = await deleteItem(itemId, weekStart)
      if (openItem.current === itemId) setOpen(null)
      // Only replace the displayed week if it's still the one being viewed;
      // other weeks were dropped from the cache and reload when viewed.
      const show = weekAfterDelete(viewing.current, week)
      if (show) {
        setResult({ for: show.week_start, status: 'ready', week: show })
        document.querySelector<HTMLElement>('.week-body')?.focus()
      }
    } catch (error) {
      if (error instanceof WeekError && error.kind === 'missing') {
        // Already gone (say, deleted in another tab): close and reload, no error.
        if (openItem.current === itemId) setOpen(null)
        clearWeekCache()
        setResult(undefined)
        setReload((n) => n + 1)
        return
      }
      const message = error instanceof WeekError ? error.message : "Can't reach the planner."
      if (openItem.current === itemId) setDeleteErrors((errors) => ({ ...errors, [itemId]: message }))
      else setPageProblem({ title: `Couldn't delete ${title}`, body: message })
    } finally {
      setPending((ids) => {
        const rest = new Set(ids)
        rest.delete(itemId)
        return rest
      })
    }
  }

  function go(days: number) {
    const next = addDays(weekStart, days)
    window.history.pushState(null, '', `?week=${next}`)
    setWeekStart(next)
  }

  return (
    <>
      <nav className="top-bar" aria-label="Main">
        <span className="tab active" aria-current="page">
          Week
        </span>
        <div className="top-bar-actions">
          <button
            type="button"
            className="primary-button"
            onClick={() => setAdding(true)}
            disabled={state.status !== 'ready'}
          >
            New item
          </button>
        </div>
      </nav>

      {adding && state.status === 'ready' && (
        <NewItemDialog
          weekStart={weekStart}
          timezone={state.week.timezone}
          frames={state.week.frames}
          slotMin={state.week.slot_min}
          onClose={() => setAdding(false)}
          onAdded={(week) => setResult({ for: weekStart, status: 'ready', week })}
        />
      )}

      <main className="content">
        <div className="title-row">
          <div className="title-block">
            <span className="eyebrow">Your week</span>
            <h1 className="page-title">{weekTitle(weekStart)}</h1>
          </div>
          <div className="week-nav">
            <button type="button" className="icon-button" onClick={() => go(-7)} aria-label="Previous week">
              <Chevron direction="left" />
            </button>
            <button type="button" className="icon-button" onClick={() => go(7)} aria-label="Next week">
              <Chevron direction="right" />
            </button>
          </div>
        </div>

        {pageProblem && <Banner {...pageProblem} onDismiss={() => setPageProblem(null)} />}
        {state.status === 'loading' && <p className="loading">Loading...</p>}
        {state.status === 'error' && <Banner {...state.problem} />}
        {state.status === 'ready' && !state.week.feasible && (
          <Banner
            title="This week can't be planned"
            body="Some deadline, window or dependency can't be met. Check the week file's estimates and windows."
          />
        )}
        {state.status === 'ready' && state.week.feasible && (
          <>
            <WeekGrid
              week={state.week}
              onOpen={(block, opener) => setOpen({ kind: 'block', itemId: block.item_id, title: block.title, block, opener })}
            />
            {state.week.unscheduled.length > 0 && (
              <section aria-labelledby="unscheduled-label">
                <h2 id="unscheduled-label" className="section-label">
                  Unscheduled
                </h2>
                <ul className="list-card">
                  {state.week.unscheduled.map((item) => (
                    <li key={item.id} className="list-row">
                      <div className="row-text">
                        <span className="row-title">{item.title}</span>
                        {(item.estimate_min !== null || item.reason) && (
                          <span className="row-sub">
                            {item.estimate_min !== null && estimateLabel(item.estimate_min)}
                            {item.estimate_min !== null && item.reason && ' · '}
                            {item.reason && <span className="row-reason">{item.reason}</span>}
                          </span>
                        )}
                      </div>
                      <button
                        type="button"
                        className="more-button"
                        aria-label={`More about ${item.title}`}
                        aria-haspopup="dialog"
                        onClick={(event) =>
                          setOpen({ kind: 'unscheduled', itemId: item.id, title: item.title, item, opener: event.currentTarget })
                        }
                      >
                        <Dots />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </main>

      {open && state.status === 'ready' && (
        <ItemPopover
          key={open.kind === 'block' ? open.block.id : open.itemId}
          target={open}
          timezone={state.week.timezone}
          deleting={pending.has(open.itemId)}
          error={deleteErrors[open.itemId] ?? null}
          onDelete={() => remove(open)}
          onClose={closePopover}
        />
      )}
    </>
  )
}

/** What to tell the user when a week can't be shown. */
function describe(error: unknown, weekStart: DateString): Problem {
  if (error instanceof WeekError && error.kind === 'missing') {
    return { title: `Nothing to show for ${weekTitle(weekStart)} yet`, body: error.message }
  }
  if (error instanceof WeekError) {
    return { title: "This week couldn't be loaded", body: error.message }
  }
  return { title: "Can't reach the planner", body: 'Start it with uv run mycal-api in solver/.' }
}

function Banner({ title, body, onDismiss }: Problem & { onDismiss?: () => void }) {
  return (
    <div className="banner" role="status">
      <div>
        <p className="banner-title">{title}</p>
        <p className="banner-body">{body}</p>
      </div>
      {onDismiss && (
        <button type="button" className="banner-close" aria-label="Dismiss" onClick={onDismiss}>
          ×
        </button>
      )}
    </div>
  )
}

function Dots() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      {[4, 9, 14].map((x) => (
        <circle key={x} cx={x} cy="9" r="1.5" fill="none" stroke="var(--text-muted)" strokeWidth="1.5" />
      ))}
    </svg>
  )
}

function Chevron({ direction }: { direction: 'left' | 'right' }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        d={direction === 'left' ? 'M11 4 6 9l5 5' : 'M7 4l5 5-5 5'}
        fill="none"
        stroke="var(--text)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
