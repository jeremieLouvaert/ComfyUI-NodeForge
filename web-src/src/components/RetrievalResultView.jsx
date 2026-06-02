export function RetrievalResultView({ precheck, ask, onAuthorAnyway, onUseIt }) {
  const { band, hit, candidates } = precheck

  // band: core | high → show hit card
  if ((band === 'core' || band === 'high') && hit) {
    return (
      <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div>
          <div className="nf-label">Registry match</div>
          <p className="nf-muted">This may already exist in the ComfyUI ecosystem.</p>
        </div>

        <div className="nf-hit-card">
          <div className="nf-hit-tag">
            {band === 'core' ? '◆ Core match' : '▲ High confidence'}
            {hit.score != null && (
              <span className="nf-badge nf-badge-score" style={{ marginLeft: '8px' }}>
                {Math.round(hit.score * 100)}%
              </span>
            )}
          </div>
          <div className="nf-hit-title">{hit.title}</div>
          {hit.reason && <div className="nf-hit-reason">{hit.reason}</div>}
          {hit.node_name && (
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {hit.node_name && <span className="nf-badge nf-badge-muted">{hit.node_name}</span>}
              {hit.category && <span className="nf-badge nf-badge-muted">{hit.category}</span>}
              {hit.health && <span className="nf-badge nf-badge-amber">{hit.health}</span>}
            </div>
          )}
          {hit.url && (
            <a
              href={hit.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: '11px',
                color: 'var(--nf-accent)',
                textDecoration: 'none',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              View on registry ↗
            </a>
          )}

          <div className="nf-hit-actions">
            <button
              className="nf-btn nf-btn-primary"
              onClick={onAuthorAnyway}
              style={{ flex: 1 }}
            >
              Author it anyway
            </button>
            <button
              className="nf-btn nf-btn-secondary"
              onClick={onUseIt}
              style={{ flex: 1 }}
            >
              I'll use that
            </button>
          </div>
        </div>
      </div>
    )
  }

  // band: middle → candidates list
  if (band === 'middle') {
    return (
      <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div>
          <div className="nf-label">Possibly related</div>
          <p className="nf-muted">No confident match — but these exist in the registry.</p>
        </div>

        {candidates && candidates.length > 0 && (
          <div className="nf-candidate-list">
            {candidates.map((c, i) => (
              <div key={i} className="nf-candidate-item" title={c.reason}>
                <div className="nf-candidate-title">{c.title}</div>
                <div className="nf-candidate-meta">
                  {c.score != null && (
                    <span className="nf-badge nf-badge-score">{Math.round(c.score * 100)}%</span>
                  )}
                  {c.health === 'DEPRECATED' && (
                    <span className="nf-badge nf-badge-red">DEPRECATED</span>
                  )}
                  {c.url && (
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: 'var(--nf-fg-3)', fontSize: '11px', textDecoration: 'none' }}
                      onClick={e => e.stopPropagation()}
                    >
                      Registry ↗
                    </a>
                  )}
                  {c.reason && (
                    <span className="nf-caption" style={{ fontStyle: 'italic' }}>{c.reason}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <button className="nf-btn nf-btn-primary nf-btn-full" onClick={onAuthorAnyway}>
          Author a new node
        </button>
      </div>
    )
  }

  // Fallback (low / unexpected) — shouldn't render but handle gracefully
  return (
    <div className="nf-fade-in">
      <p className="nf-muted">No close matches found. Proceeding to author…</p>
    </div>
  )
}
