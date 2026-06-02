import { useState } from 'react'

export function TerminalView({ data, onStartOver, onRestart }) {
  const { type, title, detail, class_name, live_registered, status } = data
  const [restarting, setRestarting] = useState(false)

  async function handleRestart() {
    setRestarting(true)
    await onRestart()
  }

  if (type === 'banked') {
    const displayTitle = title || class_name || 'Node'
    return (
      <div className="nf-fade-in nf-success-card">
        <div className="nf-success-icon">✓</div>
        <div className="nf-success-title">{displayTitle} installed</div>
        {live_registered ? (
          <>
            <p className="nf-success-sub">
              The node is live and registered — no restart needed.
            </p>
            <button className="nf-btn nf-btn-secondary" onClick={onStartOver}>
              Build another
            </button>
          </>
        ) : (
          <>
            <p className="nf-success-sub">
              The node was installed but ComfyUI needs a restart to register it.
            </p>
            {restarting ? (
              <div className="nf-working-label">
                <span className="nf-pulse-dot" />
                Restarting… page will reload shortly.
              </div>
            ) : (
              <button className="nf-btn nf-btn-primary" onClick={handleRestart}>
                Restart ComfyUI to use your new node
              </button>
            )}
            <button className="nf-btn nf-btn-ghost" onClick={onStartOver} style={{ marginTop: '-4px' }}>
              Build another (restart later)
            </button>
          </>
        )}
      </div>
    )
  }

  if (type === 'rejected') {
    return (
      <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div className="nf-callout nf-callout-amber">
          <div className="nf-callout-title">Rejected — nothing was installed</div>
          {detail && <p style={{ margin: '4px 0 0', fontSize: '12px', opacity: 0.85 }}>{detail}</p>}
        </div>
        <button className="nf-btn nf-btn-secondary nf-btn-full" onClick={onStartOver}>
          Start over
        </button>
      </div>
    )
  }

  if (type === 'exists') {
    return (
      <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div className="nf-callout nf-callout-amber">
          <div className="nf-callout-title">Node already exists</div>
          {(detail || status) && (
            <p style={{ margin: '4px 0 0', fontSize: '12px', opacity: 0.85 }}>
              {detail || status}
            </p>
          )}
        </div>
        <button className="nf-btn nf-btn-secondary nf-btn-full" onClick={onStartOver}>
          Start over
        </button>
      </div>
    )
  }

  if (type === 'cancelled') {
    return (
      <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div className="nf-callout nf-callout-amber">
          <div className="nf-callout-title">Cancelled</div>
        </div>
        <button className="nf-btn nf-btn-secondary nf-btn-full" onClick={onStartOver}>
          Start over
        </button>
      </div>
    )
  }

  // error (default)
  return (
    <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div className="nf-callout nf-callout-red">
        <div className="nf-callout-title">Error</div>
        {detail && (
          <p style={{ margin: '4px 0 0', fontSize: '12px', opacity: 0.9, fontFamily: 'var(--nf-font-mono)' }}>
            {detail}
          </p>
        )}
      </div>
      <button className="nf-btn nf-btn-secondary nf-btn-full" onClick={onStartOver}>
        Start over
      </button>
    </div>
  )
}
