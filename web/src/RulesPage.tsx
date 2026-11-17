import { useEffect, useRef, useState } from 'react'
import { listFrames, WeekError } from './api'
import { FrameDialog } from './FrameDialog'
import { frameDetail, frameLabel, type FrameOut } from './frameForm'
import type { DateString } from './time'

interface Props {
  week: DateString // the week last viewed; changes return it and the Week tab shows it
}

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; rows: T[] }

/** The Frames and rules page (web/DESIGN.md, "Frames and rules"). */
export function RulesPage({ week }: Props) {
  const [frames, setFrames] = useState<Load<FrameOut>>({ status: 'loading' })
  const [reload, setReload] = useState(0)
  // The frame dialog: closed, adding, or editing a frame.
  const [frameDialog, setFrameDialog] = useState<{ editing?: FrameOut } | null>(null)
  // Where focus goes once the list has reloaded: a saved row, or the add button after a delete.
  const focusAfter = useRef<{ ids: Set<string>; edited?: string } | 'add-frame' | null>(null)

  useEffect(() => {
    let current = true
    listFrames()
      .then((rows) => current && setFrames({ status: 'ready', rows }))
      .catch((error: unknown) => {
        if (current) setFrames({ status: 'error', message: error instanceof WeekError ? error.message : "Can't reach the planner." })
      })
    return () => {
      current = false
    }
  }, [reload])

  // After a save, focus the saved row (the new one when adding); after a delete, the add button.
  useEffect(() => {
    const target = focusAfter.current
    if (frames.status !== 'ready' || !target) return
    focusAfter.current = null
    if (target === 'add-frame') {
      document.getElementById('add-frame')?.focus()
      return
    }
    const id = target.edited ?? frames.rows.find((row) => !target.ids.has(row.id))?.id
    if (id) document.querySelector<HTMLElement>(`[data-frame="${id}"]`)?.focus()
  }, [frames])

  function saved(editing: FrameOut | undefined, deleted: boolean) {
    const ids = new Set(frames.status === 'ready' ? frames.rows.map((row) => row.id) : [])
    focusAfter.current = deleted ? 'add-frame' : { ids, edited: editing?.id }
    setReload((n) => n + 1)
  }

  return (
    <main className="content">
      <div className="title-row">
        <div className="title-block">
          <span className="eyebrow">Your planner</span>
          <h1 className="page-title">Frames and rules</h1>
        </div>
      </div>

      {frames.status === 'error' && (
        <div className="banner" role="status">
          <div>
            <p className="banner-title">Couldn't load frames and rules</p>
            <p className="banner-body">{frames.message}</p>
          </div>
        </div>
      )}

      <div className="rules-column">
        <section aria-labelledby="frames-label">
          <SectionHeader
            id="frames-label"
            label="Work frames"
            description="Times when flexible work may be placed, every week."
            addId="add-frame"
            addLabel="Add frame"
            disabled={frames.status !== 'ready'}
            onAdd={() => setFrameDialog({})}
          />
          <div className="list-card">
            {frames.status === 'loading' && <p className="empty-row">Loading...</p>}
            {frames.status === 'ready' && frames.rows.length === 0 && (
              <p className="empty-row">No work frames. Items without their own times can't be placed until you add one.</p>
            )}
            {frames.status === 'ready' &&
              frames.rows.map((frame) => (
                <button
                  key={frame.id}
                  type="button"
                  className="edit-row"
                  data-frame={frame.id}
                  aria-label={frameLabel(frame)}
                  onClick={() => setFrameDialog({ editing: frame })}
                >
                  <span className="row-text">
                    <span className="row-title">{frame.name}</span>
                    <span className="row-sub">{frameDetail(frame)}</span>
                  </span>
                  <RowChevron />
                </button>
              ))}
          </div>
        </section>
      </div>

      {frameDialog && (
        <FrameDialog
          key={frameDialog.editing?.id ?? 'new'}
          week={week}
          editing={frameDialog.editing}
          onClose={() => setFrameDialog(null)}
          onSaved={() => saved(frameDialog.editing, false)}
          onDeleted={() => saved(frameDialog.editing, true)}
        />
      )}
    </main>
  )
}

interface HeaderProps {
  id: string
  label: string
  description: string
  addId: string
  addLabel: string
  disabled: boolean
  onAdd: () => void
}

function SectionHeader({ id, label, description, addId, addLabel, disabled, onAdd }: HeaderProps) {
  return (
    <div className="section-header">
      <div className="section-text">
        <h2 id={id} className="section-label">
          {label}
        </h2>
        <p className="section-description">{description}</p>
      </div>
      <button id={addId} type="button" className="secondary-button add-button" disabled={disabled} onClick={onAdd}>
        <Plus />
        {addLabel}
      </button>
    </div>
  )
}

function Plus() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path d="M9 3.5v11M3.5 9h11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function RowChevron() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="row-chevron">
      <path d="M7 4l5 5-5 5" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
