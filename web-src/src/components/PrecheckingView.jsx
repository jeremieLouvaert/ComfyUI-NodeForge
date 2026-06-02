export function PrecheckingView({ ask }) {
  return (
    <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <div className="nf-label">Searching registry</div>
        <p className="nf-muted" style={{ marginBottom: '12px' }}>
          Checking if a node already does this…
        </p>
        <div className="nf-card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <p className="nf-caption" style={{ fontStyle: 'italic' }}>"{ask}"</p>
          <div className="nf-skeleton" style={{ height: '12px', width: '80%' }} />
          <div className="nf-skeleton" style={{ height: '12px', width: '55%' }} />
          <div className="nf-skeleton" style={{ height: '12px', width: '65%' }} />
        </div>
      </div>
    </div>
  )
}
