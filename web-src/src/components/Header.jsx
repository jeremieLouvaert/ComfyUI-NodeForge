// Header — sticky, always visible, shows NodeForge branding + cancel/reset

export function Header({ onStartOver, canCancel }) {
  return (
    <div className="nf-header">
      <svg className="nf-header-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        {/* Forge/anvil glyph */}
        <path d="M3 14h14v1.5a.5.5 0 0 1-.5.5h-13a.5.5 0 0 1-.5-.5V14z" fill="currentColor" opacity=".4"/>
        <path d="M6 14V9.5C6 8.12 7.12 7 8.5 7h3C12.88 7 14 8.12 14 9.5V14H6z" fill="currentColor" opacity=".7"/>
        <path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h1A1.5 1.5 0 0 1 12 5.5V7H8z" fill="currentColor"/>
        <path d="M14 9h2.5a.5.5 0 0 1 0 1H14V9z" fill="currentColor" opacity=".5"/>
      </svg>
      <span className="nf-header-title">NodeForge</span>
      <div className="nf-header-actions">
        {canCancel && (
          <button
            className="nf-btn nf-btn-ghost"
            onClick={onStartOver}
            title="Cancel and start over"
          >
            ✕ Cancel
          </button>
        )}
        {!canCancel && (
          <button
            className="nf-btn nf-btn-ghost"
            style={{ visibility: 'hidden', pointerEvents: 'none' }}
            aria-hidden="true"
          >
            placeholder
          </button>
        )}
      </div>
    </div>
  )
}
