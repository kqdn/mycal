import type { Proposal } from './api'
import { changeCount, overlapLines, type Change } from './proposal'

// The compare view (web/DESIGN.md, "Compare view"): the controls in the title row, and the changes card above the grid.

interface ControlsProps {
  showProposal: boolean
  answering: 'accept' | 'discard' | null // which button is running
  onShow: (proposal: boolean) => void
  onAccept: () => void
  onDiscard: () => void
}

/**
 * One toggle that names the plan on screen ("New plan" green and filled, "Current plan" white and
 * outlined) and flips to the other, then Discard and Accept. Accept only from the new plan, so you
 * see what you accept. On screen the proposal is "the new plan".
 */
export function CompareControls({ showProposal, answering, onShow, onAccept, onDiscard }: ControlsProps) {
  const busy = answering !== null
  return (
    <div className="compare-controls">
      <button
        type="button"
        className={showProposal ? 'compare-toggle showing-new' : 'compare-toggle'}
        aria-label={showProposal ? 'Switch to current plan' : 'Switch to new plan'}
        title={showProposal ? 'Switch to current plan (S)' : 'Switch to new plan (S)'}
        onClick={() => onShow(!showProposal)}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7" />
        </svg>
        {/* Both labels share one cell, so the button is as wide as the longer one and doesn't jump. */}
        <span className="compare-toggle-labels">
          <span className={showProposal ? '' : 'hidden'}>New plan</span>
          <span className={showProposal ? 'hidden' : ''}>Current plan</span>
        </span>
      </button>
      <button type="button" className="secondary-button" disabled={busy} onClick={onDiscard}>
        {answering === 'discard' ? 'Discarding...' : 'Discard'}
      </button>
      <button
        type="button"
        className="primary-button"
        disabled={busy || !showProposal}
        title={showProposal ? undefined : 'Switch to the new plan to accept it'}
        onClick={onAccept}
      >
        {answering === 'accept' ? 'Accepting...' : 'Accept'}
      </button>
    </div>
  )
}

interface CardProps {
  proposal: Proposal
  changes: Change[]
  showProposal: boolean
  selected: string | null // the block id of the selected change
  error: string | null
  onSelect: (blockId: string) => void // a tile was clicked: show that change in the grid, or let go of it
}

/** What the proposal changes in this week, one tile per change, then what didn't fit. */
export function ChangesCard({ proposal, changes, showProposal, selected, error, onSelect }: CardProps) {
  const overlaps = overlapLines(proposal)
  const hint = showProposal
    ? 'Orange outlines are the new spots in the new plan. Click a change to jump to it and see where it was.'
    : 'Orange outlines are blocks the new plan changes. Click a change to jump to it and see where it goes.'
  return (
    <section className="changes-card" aria-labelledby="changes-title">
      <div className="changes-head">
        <p className="changes-title" id="changes-title">
          {changes.length === 0 ? 'Nothing changes in this week' : changeCount(changes.length)}
        </p>
        {changes.length > 0 && <p className="changes-hint">{hint}</p>}
      </div>

      {changes.length > 0 && (
        <div className="change-tiles">
          {changes.map((change) => (
            <button
              key={change.blockId}
              type="button"
              className="change-tile"
              aria-pressed={selected === change.blockId}
              onClick={() => onSelect(change.blockId)}
            >
              <span className="change-tile-text-block">
                <span className="change-tile-title">{change.title}</span>
                <span className="change-tile-text">{change.text}</span>
              </span>
              <span className="change-tile-show">{selected === change.blockId ? 'Showing' : 'Show'}</span>
            </button>
          ))}
        </div>
      )}

      {proposal.left_over.length > 0 && (
        <div>
          <p className="changes-label">Didn't fit</p>
          <ul className="left-over-list" aria-label="Didn't fit">
            {proposal.left_over.map((item) => (
              <li key={item.item_id} className="left-over-row">
                <span className="row-title">{item.title}</span>
                <span className="row-sub row-reason">{item.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {overlaps.map((line) => (
        <p key={line} className="changes-overlap">
          {line}
        </p>
      ))}

      {error && <p className="field-error">{error}</p>}
    </section>
  )
}
