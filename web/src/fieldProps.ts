// The attributes that tie a dialog field to its error message (see fields.tsx).

/** Marks the field Add goes to, and ties it to its error for screen readers. */
export function fieldProps<F extends string>(field: F, shown: (field: F) => string | undefined) {
  const message = shown(field)
  return {
    'data-field': field,
    'aria-invalid': message ? true : undefined,
    'aria-describedby': message ? `${field}-error` : undefined,
  }
}
