import { useState } from 'react'
import { FieldError } from './fields'
import { pickerRows, targetLine, type TargetOut } from './ruleForm'

interface Props {
  available: TargetOut[] | null // null while loading
  loadError: string | null
  everyItem: boolean
  picked: TargetOut[]
  error?: string
  onChange: (changes: { everyItem?: boolean; picked?: TargetOut[] }) => void
}

/** "Applies to": every item, or chosen items from a filterable list (DESIGN.md, Target picker). */
export function TargetPicker({ available, loadError, everyItem, picked, error, onChange }: Props) {
  const [filter, setFilter] = useState('')
  const pickedIds = new Set(picked.map((t) => t.id))
  const rows = pickerRows(available ?? [], picked, filter)

  function toggle(target: TargetOut) {
    onChange({ picked: pickedIds.has(target.id) ? picked.filter((t) => t.id !== target.id) : [...picked, target] })
  }

  return (
    <div className="field">
      <span className="field-label" id="applies-to-label">
        Applies to
      </span>
      <div className="segmented-pair" role="group" aria-labelledby="applies-to-label">
        <button
          type="button"
          aria-pressed={everyItem}
          className={everyItem ? 'segment selected' : 'segment'}
          onClick={() => onChange({ everyItem: true })}
        >
          Every item
        </button>
        <button
          type="button"
          aria-pressed={!everyItem}
          data-field="targets"
          aria-describedby={error ? 'targets-error' : undefined}
          className={!everyItem ? 'segment selected' : 'segment'}
          onClick={() => onChange({ everyItem: false })}
        >
          Chosen items
        </button>
      </div>

      {!everyItem && (
        <div className="target-list">
          <input
            type="search"
            className="text-input filter-input"
            placeholder="Filter items"
            aria-label="Filter items"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            autoComplete="off"
          />
          {picked.length > 0 && <p className="picked-count">{picked.length} picked</p>}
          <div className="target-card" role="group" aria-label="Items">
            {available === null && !loadError && <p className="target-empty">Loading...</p>}
            {loadError && <p className="target-empty">Couldn't load items: {loadError}</p>}
            {available !== null && rows.length === 0 && (
              <p className="target-empty">{filter.trim() ? `No items match "${filter.trim()}".` : 'No items to pick yet.'}</p>
            )}
            {rows.map((target) => {
              const on = pickedIds.has(target.id)
              return (
                <label key={target.id} className="target-row">
                  <input type="checkbox" className="visually-hidden" checked={on} onChange={() => toggle(target)} />
                  <span className={on ? 'checkbox checked' : 'checkbox'} aria-hidden="true">
                    {on && (
                      <svg width="14" height="14" viewBox="0 0 14 14">
                        <path
                          d="M3 7.5 5.75 10 11 4"
                          fill="none"
                          stroke="var(--accent-contrast)"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    )}
                  </span>
                  <span className="row-text">
                    <span className="target-title">{target.title}</span>
                    {targetLine(target) && <span className="row-sub">{targetLine(target)}</span>}
                  </span>
                </label>
              )
            })}
          </div>
        </div>
      )}
      <FieldError field="targets" message={error} />
    </div>
  )
}
