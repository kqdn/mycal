import type { Block, Proposal } from './api'
import { overlapLines, proposalChanges } from './proposal'

interface Props {
  proposal: Proposal
  current: Block[] // the week's blocks in the current plan
  timezone: string
  showProposal: boolean
  answering: 'accept' | 'discard' | null // which button is running
  error: string | null
  onShow: (proposal: boolean) => void
  onAccept: () => void
  onDiscard: () => void
}

/**
 * The compare view's banner (web/DESIGN.md, "Compare view"): what the waiting change is, a
 * Current plan / Proposal toggle for the grid, what moves in this week, and what didn't fit.
 */
export function ProposalBanner({ proposal, current, timezone, showProposal, answering, error, onShow, onAccept, onDiscard }: Props) {
  const changes = proposalChanges(current, proposal.blocks, timezone)
  const overlaps = overlapLines(proposal)
  const busy = answering !== null
  return (
    <section className="banner proposal-banner" aria-labelledby="proposal-title">
      <div className="proposal-head">
        <div className="row-text">
          <span className="proposal-eyebrow">Proposed change</span>
          <p className="banner-title" id="proposal-title">
            {proposal.summary}
          </p>
        </div>
        <div className="proposal-actions">
          <button type="button" className="secondary-button" disabled={busy} onClick={onDiscard}>
            {answering === 'discard' ? 'Discarding...' : 'Discard'}
          </button>
          <button type="button" className="primary-button" disabled={busy} onClick={onAccept}>
            {answering === 'accept' ? 'Accepting...' : 'Accept'}
          </button>
        </div>
      </div>

      <div className="segmented-pair proposal-toggle" role="radiogroup" aria-label="Show in the grid">
        {[
          { value: false, label: 'Current plan' },
          { value: true, label: 'Proposal' },
        ].map(({ value, label }) => (
          <button
            key={label}
            type="button"
            role="radio"
            aria-checked={showProposal === value}
            className={showProposal === value ? 'segment selected' : 'segment'}
            onClick={() => onShow(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {changes.length === 0 ? (
        <p className="banner-body">Nothing changes in this week.</p>
      ) : (
        <ul className="proposal-list" aria-label="Changes in this week">
          {changes.map((change) => (
            <li key={change.blockId} className="proposal-row">
              <span className="row-title">{change.title}</span>
              <span className="row-sub">{change.text}</span>
            </li>
          ))}
        </ul>
      )}

      {proposal.left_over.length > 0 && (
        <>
          <p className="proposal-label">Didn't fit</p>
          <ul className="proposal-list" aria-label="Didn't fit">
            {proposal.left_over.map((item) => (
              <li key={item.item_id} className="proposal-row">
                <span className="row-title">{item.title}</span>
                <span className="row-sub row-reason">{item.message}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {overlaps.map((line) => (
        <p key={line} className="banner-body proposal-overlap">
          {line}
        </p>
      ))}

      {error && <p className="field-error">{error}</p>}
    </section>
  )
}
