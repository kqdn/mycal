import { useEffect, useRef, useState } from 'react'
import { listFrames, listRules, loadWeek, WeekError } from './api'
import { FrameDialog } from './FrameDialog'
import { frameDetail, frameLabel, type FrameOut } from './frameForm'
import { RuleDialog } from './RuleDialog'
import { ruleDetail, ruleFormFrom, ruleLabel, ruleSentence, sortRules, type RuleOut } from './ruleForm'
import type { DateString } from './time'

interface Props {
  week: DateString // the week last viewed; changes return it and the Week tab shows it
}

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; rows: T[] }
type Focus = { section: 'frame' | 'rule'; ids: Set<string>; edited?: string; deleted: boolean }

/** The Frames and rules page (web/DESIGN.md, "Frames and rules"). */
export function RulesPage({ week }: Props) {
  const [frames, setFrames] = useState<Load<FrameOut>>({ status: 'loading' })
  const [rules, setRules] = useState<Load<RuleOut>>({ status: 'loading' })
  const [reload, setReload] = useState(0)
  // The planner's slot size, for "Planned as" under a daily limit. From the week, never hardcoded.
  const [slotMin, setSlotMin] = useState<number | null>(null)
  // The open dialog: closed, or adding or editing a frame or a rule.
  const [frameDialog, setFrameDialog] = useState<{ editing?: FrameOut } | null>(null)
  const [ruleDialog, setRuleDialog] = useState<{ editing?: RuleOut } | null>(null)
  // Where focus goes once the lists have reloaded: a saved row, or the section's add button after a delete.
  const focusAfter = useRef<Focus | null>(null)

  useEffect(() => {
    let current = true
    const failed = (error: unknown) => ({
      status: 'error' as const,
      message: error instanceof WeekError ? error.message : "Can't reach the planner.",
    })
    listFrames()
      .then((rows) => current && setFrames({ status: 'ready', rows }))
      .catch((error: unknown) => current && setFrames(failed(error)))
    listRules()
      .then((rows) => current && setRules({ status: 'ready', rows: sortRules(rows) }))
      .catch((error: unknown) => current && setRules(failed(error)))
    return () => {
      current = false
    }
  }, [reload])

  useEffect(() => {
    loadWeek(week)
      .then((loaded) => setSlotMin(loaded.slot_min))
      .catch(() => setSlotMin(null))
  }, [week])

  // After a save, focus the saved row (the new one when adding); after a delete, the add button.
  useEffect(() => {
    const target = focusAfter.current
    if (!target) return
    const list = target.section === 'frame' ? frames : rules
    if (list.status !== 'ready') return
    focusAfter.current = null
    if (target.deleted) {
      document.getElementById(`add-${target.section}`)?.focus()
      return
    }
    const id = target.edited ?? list.rows.find((row) => !target.ids.has(row.id))?.id
    if (id) document.querySelector<HTMLElement>(`[data-${target.section}="${id}"]`)?.focus()
  }, [frames, rules])

  function saved(section: 'frame' | 'rule', editing: { id: string } | undefined, deleted: boolean) {
    const list = section === 'frame' ? frames : rules
    const ids = new Set(list.status === 'ready' ? list.rows.map((row) => row.id) : [])
    focusAfter.current = { section, ids, edited: editing?.id, deleted }
    setReload((n) => n + 1)
  }

  const loadError = frames.status === 'error' ? frames.message : rules.status === 'error' ? rules.message : null

  return (
    <main className="content">
      <div className="title-row">
        <div className="title-block">
          <span className="eyebrow">Your planner</span>
          <h1 className="page-title">Frames and rules</h1>
        </div>
      </div>

      {loadError && (
        <div className="banner" role="status">
          <div>
            <p className="banner-title">Couldn't load frames and rules</p>
            <p className="banner-body">{loadError}</p>
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

        <section aria-labelledby="rules-label">
          <SectionHeader
            id="rules-label"
            label="Rules"
            description="Limits and wishes the planner follows when it places work."
            addId="add-rule"
            addLabel="Add rule"
            disabled={rules.status !== 'ready'}
            onAdd={() => setRuleDialog({})}
          />
          <div className="list-card">
            {rules.status === 'loading' && <p className="empty-row">Loading...</p>}
            {rules.status === 'ready' && rules.rows.length === 0 && (
              <p className="empty-row">No rules yet. The planner only uses your work frames and each item's times.</p>
            )}
            {rules.status === 'ready' &&
              rules.rows.map((rule) => (
                <button
                  key={rule.id}
                  type="button"
                  className="edit-row"
                  data-rule={rule.id}
                  aria-label={ruleLabel(rule)}
                  onClick={() => setRuleDialog({ editing: rule })}
                >
                  <span className="row-text">
                    <span className="row-title">{ruleSentence(ruleFormFrom(rule))}</span>
                    <span className="row-sub">{ruleDetail(rule)}</span>
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
          onSaved={() => saved('frame', frameDialog.editing, false)}
          onDeleted={() => saved('frame', frameDialog.editing, true)}
        />
      )}

      {ruleDialog && (
        <RuleDialog
          key={ruleDialog.editing?.id ?? 'new'}
          week={week}
          slotMin={slotMin}
          editing={ruleDialog.editing}
          onClose={() => setRuleDialog(null)}
          onSaved={() => saved('rule', ruleDialog.editing, false)}
          onDeleted={() => saved('rule', ruleDialog.editing, true)}
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
