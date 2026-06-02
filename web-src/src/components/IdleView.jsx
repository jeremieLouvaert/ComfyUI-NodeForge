import { useState } from 'react'

export function IdleView({ onSubmit, model, setModel, n, setN }) {
  const [ask, setAsk] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)

  function handleSubmit(e) {
    e.preventDefault()
    const trimmed = ask.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }

  return (
    <div className="nf-fade-in">
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div>
          <label className="nf-label" htmlFor="nf-ask">Describe your node</label>
          <textarea
            id="nf-ask"
            className="nf-textarea"
            value={ask}
            onChange={e => setAsk(e.target.value)}
            placeholder="e.g. A node that sharpens an image using unsharp masking, with radius and amount controls…"
            rows={4}
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(e)
            }}
          />
        </div>

        <button
          type="submit"
          className="nf-btn nf-btn-primary nf-btn-full"
          disabled={!ask.trim()}
        >
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
            <path d="M6.5 1v11M1 6.5h11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          Build node
        </button>

        <div className="nf-advanced">
          <button
            type="button"
            className="nf-advanced-toggle"
            onClick={() => setShowAdvanced(v => !v)}
            aria-expanded={showAdvanced}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true"
              style={{ transform: showAdvanced ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 150ms' }}>
              <path d="M3 2l4 3-4 3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Advanced
          </button>

          {showAdvanced && (
            <div className="nf-controls-row nf-fade-in">
              <div>
                <label className="nf-label" htmlFor="nf-model">Model</label>
                <select
                  id="nf-model"
                  className="nf-select"
                  value={model}
                  onChange={e => setModel(e.target.value)}
                >
                  <option value="claude-sonnet-4-6">Sonnet 4.6</option>
                  <option value="claude-opus-4-8">Opus 4.8</option>
                  <option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
                </select>
              </div>
              <div>
                <label className="nf-label" htmlFor="nf-n">Attempts (n)</label>
                <select
                  id="nf-n"
                  className="nf-select"
                  value={n}
                  onChange={e => setN(Number(e.target.value))}
                >
                  {[1, 2, 3, 4, 5].map(v => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>
      </form>

      <div className="nf-divider" style={{ marginTop: '24px' }} />
      <p className="nf-caption" style={{ textAlign: 'center', paddingTop: '4px' }}>
        NodeForge will search existing nodes, then author, test, and install a new one.
      </p>
    </div>
  )
}
