import { SHORTCUTS } from './shortcuts'
import { HELP_ID } from './useShortcuts'

/**
 * The list of keyboard shortcuts (web/DESIGN.md, "Keyboard shortcuts"). A
 * native popover="auto", so ? or the top bar's button opens it, and Escape or
 * a click outside closes it, with no state of its own.
 */
export function ShortcutsHelp() {
  return (
    <div id={HELP_ID} popover="auto" className="shortcuts-help" role="dialog" aria-labelledby="shortcuts-title">
      <p id="shortcuts-title" className="popover-title">
        Keyboard shortcuts
      </p>
      <dl className="shortcut-list">
        {SHORTCUTS.map(({ keys, label, where }) => (
          <div key={label} className="shortcut-row">
            <dt className="shortcut-keys">
              {keys.map((key, i) => (
                <span key={key}>
                  {i > 0 && <span className="shortcut-or"> or </span>}
                  <kbd>{key}</kbd>
                </span>
              ))}
            </dt>
            <dd className="shortcut-label">
              {label}
              <span className="shortcut-where">{where}</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="hint">Shortcuts don't work while you type in a field or a dialog is open.</p>
    </div>
  )
}
