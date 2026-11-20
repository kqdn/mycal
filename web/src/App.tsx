import { useCallback, useEffect, useRef, useState } from 'react'
import {
  acceptProposal,
  clearWeekCache,
  deleteItem,
  deleteSeries,
  discardProposal,
  getItem,
  getSeries,
  listCheckIns,
  loadWeek,
  peekWeek,
  WeekError,
  type CheckIn,
  type Week,
} from './api'
import { CheckInDialog } from './CheckInDialog'
import { bannerTitle, pendingKey, targetFromBlock, type CheckInTarget } from './checkIn'
import { weekAfterDelete, whenLine } from './itemDetails'
import { formAt, formFrom, type ItemForm } from './itemForm'
import { ItemPopover, type PopoverTarget, type Scope } from './ItemPopover'
import { NewItemDialog } from './NewItemDialog'
import { changedBlocks, otherSpot, proposalChanges, shownWeek } from './proposal'
import { ChangesCard, CompareControls } from './ProposalBanner'
import { formFromSeries } from './repeatForm'
import { RulesPage } from './RulesPage'
import { ShortcutsHelp } from './ShortcutsHelp'
import { scrollMinuteFor } from './layout'
import { addDays, estimateLabel, mondayOf, today, weekTitle, type DateString } from './time'
import { HELP_ID, pointedBlock, toggleHelp, useShortcuts } from './useShortcuts'
import { WeekGrid, type Compare } from './WeekGrid'

type Problem = { title: string; body: string }
type Result = { status: 'error'; problem: Problem } | { status: 'ready'; week: Week }
type State = { status: 'loading' } | Result
type View = 'week' | 'rules'

/** The week in the URL (?week=2026-11-16), or this week's Monday. */
function weekFromUrl(): DateString {
  const param = new URLSearchParams(window.location.search).get('week')
  return param && /^\d{4}-\d{2}-\d{2}$/.test(param) ? mondayOf(param) : mondayOf(today())
}

/** The page in the URL: ?view=rules is Frames and rules, anything else the week. */
function viewFromUrl(): View {
  return new URLSearchParams(window.location.search).get('view') === 'rules' ? 'rules' : 'week'
}

function urlFor(view: View, weekStart: DateString): string {
  return view === 'rules' ? `?view=rules&week=${weekStart}` : `?week=${weekStart}`
}

export default function App() {
  const [weekStart, setWeekStart] = useState(weekFromUrl)
  const [view, setView] = useState(viewFromUrl)
  // Each result remembers which week it is for; a newer week shows as loading.
  const [result, setResult] = useState<{ for: DateString } & Result>()
  const [adding, setAdding] = useState(false)
  // The New item form a click on an empty slot starts from (its day and time); null for an empty one.
  const [addStart, setAddStart] = useState<ItemForm | null>(null)
  const [reload, setReload] = useState(0) // bump to fetch the viewed week again
  // The item details popover, and deletes started from it. A delete keeps
  // running after the popover closes, so its state lives here.
  const [open, setOpen] = useState<PopoverTarget | null>(null)
  const [pending, setPending] = useState<Set<string>>(new Set())
  const [deleteErrors, setDeleteErrors] = useState<Record<string, string>>({})
  const [pageProblem, setPageProblem] = useState<Problem | null>(null)
  // Editing: the item being loaded for the dialog, why that failed, and the dialog's starting point.
  const [opening, setOpening] = useState<string | null>(null)
  const [openError, setOpenError] = useState<{ itemId: string; message: string } | null>(null)
  const [editing, setEditing] = useState<{
    kind: 'item' | 'series'
    repeatable?: boolean // a one-off item, which the Repeats field can turn into a series
    id: string
    source: string | null
    form: ItemForm
    weekStart: DateString
  } | null>(null)
  // Check-ins (Milestone 7): the pending list, refreshed every minute, and the one being answered.
  const [checkIns, setCheckIns] = useState<CheckIn[]>([])
  const [checkingIn, setCheckingIn] = useState<CheckInTarget | null>(null)
  // The compare view (Milestone 8). Each is kept with the proposal (by its summary) it was for, so a new
  // proposal starts on its own version of the week with no old error: Current plan picked, Accept or
  // Discard failing, and a notice dismissed (by the week response that carried it).
  const [currentFor, setCurrentFor] = useState<string | null>(null)
  const [answering, setAnswering] = useState<'accept' | 'discard' | null>(null)
  const [proposalError, setProposalError] = useState<{ for: string; message: string } | null>(null)
  const [dismissedNotice, setDismissedNotice] = useState<Week | null>(null)
  const [selectedChange, setSelectedChange] = useState<{ for: string; blockId: string } | null>(null)
  const [reveal, setReveal] = useState(0) // bumped by a change tile, so the grid scrolls to it
  const lastPending = useRef<string | null>(null)
  const refreshCheckIns = useCallback(() => {
    listCheckIns()
      .then((list) => {
        // The server turns old check-ins into unanswered ones, which can re-plan, so a change it made reloads the week.
        const key = pendingKey(list)
        if (lastPending.current !== null && lastPending.current !== key) {
          clearWeekCache()
          setReload((n) => n + 1)
        }
        lastPending.current = key
        setCheckIns(list)
      })
      .catch(() => {}) // the week's own banner says when the planner can't be reached
  }, [])
  useEffect(() => {
    refreshCheckIns()
    const id = window.setInterval(refreshCheckIns, 60_000)
    return () => window.clearInterval(id)
  }, [refreshCheckIns])
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
  const proposal = state.status === 'ready' ? (state.week.proposal ?? null) : null
  const waiting = proposal !== null
  const showCurrent = proposal !== null && currentFor === proposal.summary
  // What the grid and Unscheduled show: the proposal's version of the week unless Current plan is picked.
  const shown = state.status === 'ready' ? shownWeek(state.week, !showCurrent) : null
  // The grid scrolls to what the proposal changes, the same spot in both plans.
  const focusMinute =
    state.status === 'ready' && proposal
      ? scrollMinuteFor(changedBlocks(state.week), state.week.week_start, state.week.timezone)
      : null
  const focus = proposal && focusMinute !== null ? { key: proposal.summary, minute: focusMinute } : null
  // What the proposal changes in this week, the selected change (a tile or a changed block), and what the grid draws for them.
  const changes = state.status === 'ready' && proposal ? proposalChanges(state.week.blocks, proposal.blocks, state.week.timezone) : []
  const selected = proposal && selectedChange?.for === proposal.summary ? selectedChange.blockId : null
  const selectChange = (blockId: string) =>
    proposal && setSelectedChange(selected === blockId ? null : { for: proposal.summary, blockId })
  const selectedRow = changes.find((c) => c.blockId === selected) ?? null
  const compare: Compare | null = proposal
    ? {
        tags: new Map(
          changes.flatMap((c) => {
            const text = showCurrent ? c.tagCurrent : c.tagProposal
            return text === null ? [] : [[c.blockId, { text, arrow: c.arrow }] as const]
          }),
        ),
        selected,
        other: selectedRow ? otherSpot(selectedRow, !showCurrent) : null,
        onSelect: selectChange,
        reveal,
      }
    : null
  // Something the server says once, like "the proposed change was dropped", until dismissed.
  const notice = state.status === 'ready' && state.week !== dismissedNotice ? (state.week.notice ?? null) : null

  useEffect(() => {
    const onPop = () => {
      setWeekStart(weekFromUrl())
      setView(viewFromUrl())
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // Frames and rules reach every week, so the Week page fetches its week again
  // each time it is shown after that page.
  const lastView = useRef(view)
  useEffect(() => {
    if (view === 'week' && lastView.current === 'rules') {
      clearWeekCache()
      setResult(undefined)
      setReload((n) => n + 1)
    }
    lastView.current = view
  }, [view])

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

  async function remove(target: PopoverTarget, scope: Scope) {
    const { itemId, title } = target
    const seriesId = seriesOf(target)
    setPending((ids) => new Set(ids).add(itemId))
    setDeleteErrors((errors) => {
      const rest = { ...errors }
      delete rest[itemId]
      return rest
    })
    try {
      // "This one" on an occurrence deletes the item; the server skips its date so it doesn't come back.
      const week =
        scope === 'series' && seriesId ? await deleteSeries(seriesId, weekStart) : await deleteItem(itemId, weekStart)
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

  async function startEdit(target: PopoverTarget, scope: Scope) {
    const { itemId } = target
    const seriesId = seriesOf(target)
    setOpening(itemId)
    setOpenError(null)
    try {
      if (scope === 'series' && seriesId) {
        const series = await getSeries(seriesId)
        setOpen(null)
        const form = formFromSeries(series, today())
        setEditing({ kind: 'series', id: series.id, source: series.source, form, weekStart })
        return
      }
      const item = await getItem(itemId)
      setOpen(null)
      setEditing({
        kind: 'item',
        repeatable: item.series_id === null,
        id: item.id,
        source: item.source,
        form: formFrom(item, today()),
        weekStart: item.week_start,
      })
    } catch (error) {
      if (error instanceof WeekError && error.kind === 'missing') {
        // Already gone: close and reload, as for a delete.
        setOpen(null)
        clearWeekCache()
        setResult(undefined)
        setReload((n) => n + 1)
        return
      }
      setOpenError({ itemId, message: error instanceof WeekError ? error.message : "Can't reach the planner." })
    } finally {
      setOpening(null)
    }
  }

  function showSaved(week: Week) {
    setResult({ for: weekStart, status: 'ready', week })
    // Any change can add or settle check-ins; this week is already fresh, so don't reload it.
    lastPending.current = null
    refreshCheckIns()
  }

  async function answerProposal(accept: boolean) {
    const summary = proposal?.summary ?? ''
    setAnswering(accept ? 'accept' : 'discard')
    setProposalError(null)
    try {
      showSaved(accept ? await acceptProposal(weekStart) : await discardProposal(weekStart))
    } catch (error) {
      if (error instanceof WeekError && error.kind === 'missing') {
        // Nothing waits any more (say, a check-in saved on its own): show the week as it is.
        clearWeekCache()
        setResult(undefined)
        setReload((n) => n + 1)
        return
      }
      setProposalError({ for: summary, message: error instanceof WeekError ? error.message : "Can't reach the planner." })
    } finally {
      setAnswering(null)
    }
  }

  function go(days: number) {
    goTo(addDays(weekStart, days))
  }

  function goTo(next: DateString) {
    if (next === weekStart) return
    window.history.pushState(null, '', urlFor('week', next))
    setWeekStart(next)
  }

  // Keyboard shortcuts for the whole app (web/DESIGN.md, "Keyboard shortcuts"). The item
  // popover and the Frames and rules page handle their own keys.
  useShortcuts(view, (action) => {
    switch (action.type) {
      case 'tab':
        show(action.view)
        return true
      case 'help':
        toggleHelp()
        return true
      case 'newItem':
        if (state.status !== 'ready' || waiting) return false
        setAdding(true)
        return true
      case 'moveWeek':
        go(action.days)
        return true
      case 'thisWeek':
        goTo(mondayOf(today()))
        return true
      case 'switchPlan':
        // Same as clicking the plan toggle; nothing to switch without a proposal.
        if (!proposal) return false
        setCurrentFor(showCurrent ? null : proposal.summary)
        return true
      case 'edit':
      case 'delete':
        return !waiting && actOnPointedBlock(action.type)
      default:
        return false
    }
  })

  /** E or Delete on the block under the mouse (or with focus): Delete opens its popover on the confirm
   * step; E edits a one-off item right away, or asks "Edit which?" for a series. With a popover open,
   * only another block counts; the popover's own block (or none) is left to the popover. */
  function actOnPointedBlock(action: 'edit' | 'delete'): boolean {
    const element = pointedBlock()
    if (state.status !== 'ready' || !element) return false
    if (open?.kind === 'block' && open.block.id === element.dataset.blockId) return false
    const block = state.week.blocks.find((b) => b.id === element.dataset.blockId)
    if (!block) return false
    const target: PopoverTarget = { kind: 'block', itemId: block.item_id, title: block.title, block, opener: element }
    if (block.deleted) {
      setOpen(target) // a deleted item's kept session: says so, with nothing to do
    } else if (action === 'delete') {
      setOpen({ ...target, startAt: 'confirm' })
    } else if (!block.editable) {
      setOpen(target) // says why it can't be edited
    } else if (block.series_id && state.week.series.some((r) => r.id === block.series_id)) {
      setOpen({ ...target, startAt: 'pickEdit' })
    } else {
      setOpen(target) // shows "Opening..." and any error, and closes when the dialog opens
      startEdit(target, 'one')
    }
    return true
  }

  function show(next: View) {
    if (next === view) return
    setOpen(null)
    window.history.pushState(null, '', urlFor(next, weekStart))
    setView(next)
  }

  const tab = (name: View, label: string) => (
    <a
      className={view === name ? 'tab active' : 'tab'}
      href={urlFor(name, weekStart)}
      aria-current={view === name ? 'page' : undefined}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return // new tab or window
        event.preventDefault()
        show(name)
      }}
    >
      {label}
    </a>
  )

  return (
    <>
      <nav className="top-bar" aria-label="Main">
        {tab('week', 'Week')}
        {tab('rules', 'Frames and rules')}
        <div className="top-bar-actions">
          <button
            type="button"
            className="help-button"
            popoverTarget={HELP_ID}
            aria-label="Keyboard shortcuts"
            title="Keyboard shortcuts (?)"
          >
            ?
          </button>
          {view === 'week' && (
            <button
              type="button"
              className="primary-button"
              onClick={() => setAdding(true)}
              disabled={state.status !== 'ready' || waiting}
              title={waiting ? 'Accept or Discard the proposed change first' : undefined}
            >
              New item
            </button>
          )}
        </div>
      </nav>
      <ShortcutsHelp />

      {view === 'rules' && <RulesPage week={weekStart} onChanged={() => show('week')} />}

      {view === 'week' && adding && state.status === 'ready' && (
        <NewItemDialog
          weekStart={weekStart}
          timezone={state.week.timezone}
          frames={state.week.frames}
          slotMin={state.week.slot_min}
          start={addStart ?? undefined}
          onClose={() => {
            setAdding(false)
            setAddStart(null)
          }}
          onSaved={showSaved}
        />
      )}

      {view === 'week' && checkingIn && state.status === 'ready' && (
        <CheckInDialog
          key={checkingIn.block_id}
          target={checkingIn}
          timezone={state.week.timezone}
          weekStart={weekStart}
          frames={state.week.frames}
          slotMin={state.week.slot_min}
          onClose={() => setCheckingIn(null)}
          onSaved={showSaved}
        />
      )}

      {view === 'week' && editing && state.status === 'ready' && (
        <NewItemDialog
          key={editing.id}
          weekStart={weekStart}
          timezone={state.week.timezone}
          frames={state.week.frames}
          slotMin={state.week.slot_min}
          editing={editing}
          onClose={() => setEditing(null)}
          onSaved={(week) => {
            showSaved(week)
            // The block it came from may have moved, so focus goes to the grid.
            requestAnimationFrame(() => document.querySelector<HTMLElement>('.week-body')?.focus())
          }}
        />
      )}

      {view === 'week' && (
        <main className="content">
          <div className="title-row">
            <div className="title-block">
              <span className="eyebrow">
                {proposal ? (showCurrent ? 'Your current plan' : `Previewing: ${proposal.summary}`) : 'Your week'}
              </span>
              <h1 className="page-title">{weekTitle(weekStart)}</h1>
            </div>
            {proposal && (
              <CompareControls
                showProposal={!showCurrent}
                answering={answering}
                onShow={(showProposal) => setCurrentFor(showProposal ? null : proposal.summary)}
                onAccept={() => answerProposal(true)}
                onDiscard={() => answerProposal(false)}
              />
            )}
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
          {notice && state.status === 'ready' && (
            <Banner title="Proposed change dropped" body={notice} onDismiss={() => setDismissedNotice(state.week)} />
          )}
          {state.status === 'ready' && checkIns.length > 0 && (
            <section className="banner check-in-banner" aria-labelledby="check-in-banner-title">
              <p className="banner-title" id="check-in-banner-title">
                {bannerTitle(checkIns.length)}
              </p>
              <ul className="check-in-list">
                {checkIns.map((checkIn) => (
                  <li key={checkIn.block_id} className="check-in-row">
                    <div className="row-text">
                      <span className="row-title">{checkIn.title}</span>
                      <span className="row-sub">
                        {whenLine(checkIn, state.week.timezone)}
                        {checkIn.status !== 'planned' && ' · Waiting for your choice'}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={waiting}
                      title={waiting ? 'Accept or Discard the proposed change first' : undefined}
                      onClick={() => setCheckingIn(checkIn)}
                    >
                      Check in
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {state.status === 'loading' && <p className="loading">Loading...</p>}
          {state.status === 'error' && <Banner {...state.problem} />}
          {state.status === 'ready' && proposal && (
            <ChangesCard
              proposal={proposal}
              changes={changes}
              showProposal={!showCurrent}
              selected={selected}
              error={proposalError?.for === proposal.summary ? proposalError.message : null}
              onSelect={(blockId) => {
                selectChange(blockId)
                setReveal((n) => n + 1)
              }}
              onShowWeek={goTo}
            />
          )}
          {state.status === 'ready' && (
            <>
              <WeekGrid
                week={shown ?? state.week}
                focus={focus}
                compare={compare}
                onOpen={(block, opener) => setOpen({ kind: 'block', itemId: block.item_id, title: block.title, block, opener })}
                onAdd={
                  waiting
                    ? undefined
                    : (date, minutes, lengthMin) => {
                        setOpen(null)
                        setAddStart(formAt(date, minutes, lengthMin, weekStart, today()))
                        setAdding(true)
                      }
                }
              />
              {(shown ?? state.week).unscheduled.length > 0 && (
                <section aria-labelledby="unscheduled-label">
                  <h2 id="unscheduled-label" className="section-label">
                    Unscheduled
                  </h2>
                  <ul className="list-card">
                    {(shown ?? state.week).unscheduled.map((item) => (
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
      )}

      {view === 'week' && open && state.status === 'ready' && (
        <ItemPopover
          key={open.kind === 'block' ? open.block.id : open.itemId}
          target={open}
          timezone={state.week.timezone}
          repeat={state.week.series.find((r) => r.id === seriesOf(open)) ?? null}
          deleting={pending.has(open.itemId)}
          waiting={waiting}
          error={deleteErrors[open.itemId] ?? null}
          opening={opening === open.itemId}
          openError={openError?.itemId === open.itemId ? openError.message : null}
          onEdit={(scope) => startEdit(open, scope)}
          onDelete={(scope) => remove(open, scope)}
          onCheckIn={(block) => {
            setOpen(null)
            setCheckingIn(targetFromBlock(block))
          }}
          onClose={closePopover}
        />
      )}
    </>
  )
}

/** The stored series a popover's item is an occurrence of, if any. */
function seriesOf(target: PopoverTarget): string | null {
  return (target.kind === 'block' ? target.block.series_id : target.item.series_id) ?? null
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
