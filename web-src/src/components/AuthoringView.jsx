import { useEffect, useRef } from 'react'

export function AuthoringView({ log }) {
  const logRef = useRef(null)

  // Auto-scroll to bottom as lines arrive
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [log])

  return (
    <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div className="nf-working-label">
          <span className="nf-pulse-dot" />
          Authoring
        </div>
        <span className="nf-caption">{log.length} steps</span>
      </div>

      <div className="nf-log" ref={logRef}>
        {log.length === 0 ? (
          <span className="nf-log-line" style={{ color: 'var(--nf-fg-3)' }}>Starting…</span>
        ) : (
          log.map((line, i) => (
            <span key={i} className="nf-log-line">{line}</span>
          ))
        )}
      </div>

      <p className="nf-caption" style={{ textAlign: 'center' }}>
        NodeForge is elaborating, generating, and verifying. This may take a minute.
      </p>
    </div>
  )
}
