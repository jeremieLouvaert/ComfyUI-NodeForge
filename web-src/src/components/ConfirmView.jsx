import { useState } from 'react'

export function ConfirmView({ data, api, onConfirm }) {
  const { title, ask, examples = [], invariants = [], unpinned_axes = [] } = data
  const [dropped, setDropped] = useState(new Set())
  const [addInvariantText, setAddInvariantText] = useState('')
  const [extraInvariants, setExtraInvariants] = useState([])
  const [loading, setLoading] = useState(false)

  function toggleDrop(id) {
    setDropped(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function addInvariant() {
    const val = addInvariantText.trim()
    if (!val) return
    setExtraInvariants(prev => [...prev, val])
    setAddInvariantText('')
  }

  async function handleConfirm() {
    setLoading(true)
    try {
      await onConfirm({
        drop: [...dropped],
        add_invariants: extraInvariants,
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <div className="nf-label">Confirm what NodeForge will build</div>
        <div className="nf-card" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--nf-fg)' }}>{title}</div>
          <div className="nf-muted">{ask}</div>
        </div>
      </div>

      {examples.length > 0 && (
        <div>
          <div className="nf-label">Examples</div>
          <p className="nf-caption" style={{ marginBottom: '8px' }}>
            Worked examples NodeForge checks the finished node against. Drop one (✕) only if it
            does not match what you want — that removes the check, not a feature.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {examples.map(ex => (
              <ExampleItem
                key={ex.id}
                example={ex}
                dropped={dropped.has(ex.id)}
                onToggle={() => toggleDrop(ex.id)}
                api={api}
              />
            ))}
          </div>
        </div>
      )}

      {(invariants.length > 0 || unpinned_axes.length > 0) && (
        <div>
          <div className="nf-label">Rules it must always follow</div>
          {invariants.length > 0 && (
            <div className="nf-invariants-list">
              {invariants.map((inv, i) => (
                <span key={i} className="nf-invariant-tag">
                  <span style={{ color: 'var(--nf-accent)', fontSize: '10px' }}>◆</span>
                  {inv}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div>
        <div className="nf-label">Add a rule</div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <input
            className="nf-input"
            value={addInvariantText}
            onChange={e => setAddInvariantText(e.target.value)}
            placeholder="e.g. the output must never be brighter than the original"
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addInvariant() } }}
          />
          <button
            className="nf-btn nf-btn-secondary"
            onClick={addInvariant}
            disabled={!addInvariantText.trim()}
            style={{ flexShrink: 0 }}
          >
            Add
          </button>
        </div>
        {extraInvariants.length > 0 && (
          <div className="nf-invariants-list" style={{ marginTop: '8px' }}>
            {extraInvariants.map((inv, i) => (
              <span key={i} className="nf-invariant-tag">
                <span style={{ color: 'var(--nf-accent)', fontSize: '10px' }}>+</span>
                {inv}
                <button
                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px', color: 'var(--nf-fg-3)', fontSize: '11px' }}
                  onClick={() => setExtraInvariants(prev => prev.filter((_, j) => j !== i))}
                  aria-label="Remove invariant"
                >×</button>
              </span>
            ))}
          </div>
        )}
      </div>

      <button
        className="nf-btn nf-btn-primary nf-btn-full"
        onClick={handleConfirm}
        disabled={loading}
      >
        {loading ? 'Confirming…' : 'Confirm & build'}
      </button>
    </div>
  )
}

function ExampleItem({ example, dropped, onToggle, api }) {
  const imgSrc = example.image
    ? api.apiURL(
        `/view?type=${example.image.type}&subfolder=${encodeURIComponent(example.image.subfolder)}&filename=${encodeURIComponent(example.image.filename)}&rand=${Date.now()}`
      )
    : null

  return (
    <div className={`nf-example-item${dropped ? ' dropped' : ''}`}>
      {imgSrc ? (
        <img
          src={imgSrc}
          alt={example.nl_statement}
          className="nf-example-thumb"
        />
      ) : (
        <div className="nf-example-thumb-placeholder" />
      )}
      <span className="nf-example-text">{example.nl_statement}</span>
      <button
        className={`nf-drop-btn${dropped ? ' active' : ''}`}
        onClick={onToggle}
        title={dropped ? 'Undo drop' : 'Drop this example'}
        aria-label={dropped ? 'Undo drop' : 'Drop this example'}
      >
        {dropped ? '↩' : '✕'}
      </button>
    </div>
  )
}
