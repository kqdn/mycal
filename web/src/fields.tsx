// Small pieces the dialogs share (DESIGN.md, Add item dialog): field errors
// and the selected-row check. fieldProps.ts ties a field to its error.

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
