import { useState } from 'react'

export function AmbiguityView({ data, onChoose }) {
  const { question, axis, options = [] } = data
  const [loading, setLoading] = useState(null)

  async function handleChoose(opt) {
    setLoading(opt)
    try {
      await onChoose(opt)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <div className="nf-label">Clarification needed</div>
        {axis && <p className="nf-caption" style={{ marginBottom: '4px' }}>Axis: {axis}</p>}
        <p className="nf-muted">{question}</p>
      </div>

      <div className="nf-option-list">
        {options.map((opt, i) => (
          <button
            key={i}
            className="nf-option-btn"
            onClick={() => handleChoose(opt)}
            disabled={loading !== null}
          >
            {loading === opt ? 'Choosing…' : opt}
          </button>
        ))}
      </div>
    </div>
  )
}
