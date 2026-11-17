// Small pieces the dialogs share (DESIGN.md, Add item dialog): field errors,
// the weekday picker and the selected-row check. fieldProps.ts ties a field to
// its error.

import { WEEKDAYS } from './itemForm'

export function FieldError({ field, message }: { field: string; message?: string }) {
  return message ? (
    <p className="field-error" id={`${field}-error`}>
      {message}
    </p>
  ) : null
}

export function Check() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="check">
      <path d="M4 9.5 7.5 13 14 5.5" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

interface PickerProps {
  labelledBy?: string // the id of a visible label, or
  label?: string // an accessible name when there is none
  field?: string // the error key: Add goes to the first day button, and its error is `${field}-error`
  value: number[]
  error?: string
  onChange: (weekdays: number[]) => void
}

/** Seven segmented day buttons, Mon to Sun (0 = Monday). */
export function WeekdayPicker({ labelledBy, label, field = 'weekdays', value, error, onChange }: PickerProps) {
  return (
    <div className="weekday-picker" role="group" aria-labelledby={labelledBy} aria-label={label}>
      {WEEKDAYS.map((name, day) => {
        const on = value.includes(day)
        return (
          <button
            key={name}
            type="button"
            aria-pressed={on}
            data-field={day === 0 ? field : undefined}
            aria-describedby={error ? `${field}-error` : undefined}
            className={on ? 'segment selected' : 'segment'}
            onClick={() => onChange(on ? value.filter((d) => d !== day) : [...value, day])}
          >
            {name}
          </button>
        )
      })}
    </div>
  )
}
