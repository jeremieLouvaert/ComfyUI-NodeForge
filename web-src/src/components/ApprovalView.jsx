import { useState } from 'react'
import { highlightPython } from '../utils/highlight.js'

export function ApprovalView({ data, api, onApprove, onReject }) {
  const {
    title,
    class_name,
    source = '',
    checks = [],
    unkilled_mutants = [],
    images = [],
    limited_verification = false,
    caveats = [],
  } = data

  const [showReject, setShowReject] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [approving, setApproving] = useState(false)
  const [rejecting, setRejecting] = useState(false)

  async function handleApprove() {
    setApproving(true)
    try {
      await onApprove('approve')
    } finally {
      setApproving(false)
    }
  }

  async function handleReject() {
    setRejecting(true)
    try {
      await onReject(rejectReason)
    } finally {
      setRejecting(false)
    }
  }

  const highlighted = highlightPython(source)

  return (
    <div className="nf-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* Title + identity */}
      <div className="nf-card nf-card-accent">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', flexWrap: 'wrap' }}>
          <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--nf-fg)' }}>{title}</div>
          {class_name && (
            <span className="nf-badge nf-badge-muted" style={{ fontFamily: 'var(--nf-font-mono)' }}>
              {class_name}
            </span>
          )}
        </div>
        <p className="nf-caption" style={{ marginTop: '4px' }}>
          Review the generated code, test results, and before/after images before approving.
        </p>
      </div>

      {/* Limited-verification banner — honest, prominent, never hidden */}
      {limited_verification && (
        <div className="nf-callout nf-callout-amber">
          <div className="nf-callout-title">⚠ Limited automated verification</div>
          <p style={{ margin: 0, fontSize: '11px', opacity: 0.9 }}>
            Automated checks could not fully confirm this node. Lean on the code and the
            before/after images, and review carefully before installing.
          </p>
          {caveats.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: '16px', fontSize: '11px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
              {caveats.map((c, i) => (
                <li key={i} style={{ opacity: 0.9 }}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Generated source */}
      <div>
        <div className="nf-label">Generated source</div>
        <pre
          className="nf-code-block"
          dangerouslySetInnerHTML={{ __html: highlighted }}
          aria-label="Generated Python source"
        />
      </div>

      {/* Test report */}
      {checks.length > 0 && (
        <div>
          <div className="nf-label">Test report</div>
          <div className="nf-check-list">
            {checks.map((check, i) => (
              <div key={i} className="nf-check-item">
                <div className="nf-check-name">
                  <span style={{ color: 'var(--nf-green-ok)', marginRight: '6px' }}>✓</span>
                  {check.name}
                </div>
                {check.teeth && check.teeth.length > 0 && (
                  <div className="nf-teeth-list">
                    Kills: {check.teeth.join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Residual risk — always shown honestly if present */}
      {unkilled_mutants.length > 0 && (
        <div className="nf-callout nf-callout-amber">
          <div className="nf-callout-title">⚠ Residual risk — unkilled mutants</div>
          <p style={{ marginBottom: '6px', fontSize: '11px', opacity: 0.85 }}>
            These mutations were not caught by any test. The node may still be correct, but
            the tests do not prove it for these cases.
          </p>
          <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '11px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {unkilled_mutants.map((m, i) => (
              <li key={i} style={{ opacity: 0.9 }}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Before/after images */}
      {images.length > 0 && (
        <div>
          <div className="nf-label">Before / After</div>
          <div className="nf-example-grid">
            {images.map((img, i) => (
              <ExampleImages key={i} img={img} api={api} />
            ))}
          </div>
        </div>
      )}

      {/* Approval actions */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingTop: '4px' }}>
        <button
          className="nf-btn nf-btn-approve nf-btn-full"
          onClick={handleApprove}
          disabled={approving || rejecting || showReject}
        >
          {approving ? 'Installing…' : '✓ Approve & install'}
        </button>

        {!showReject ? (
          <button
            className="nf-btn nf-btn-danger nf-btn-full"
            onClick={() => setShowReject(true)}
            disabled={approving || rejecting}
          >
            Reject
          </button>
        ) : (
          <div className="nf-reject-area">
            <label className="nf-label" htmlFor="nf-reject-reason">Reason (optional)</label>
            <textarea
              id="nf-reject-reason"
              className="nf-textarea"
              value={rejectReason}
              onChange={e => setRejectReason(e.target.value)}
              placeholder="Describe what's wrong or what you'd change…"
              rows={3}
            />
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                className="nf-btn nf-btn-danger"
                onClick={handleReject}
                disabled={rejecting}
                style={{ flex: 1 }}
              >
                {rejecting ? 'Rejecting…' : 'Confirm reject'}
              </button>
              <button
                className="nf-btn nf-btn-secondary"
                onClick={() => setShowReject(false)}
                disabled={rejecting}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function makeImgUrl(api, descriptor) {
  if (!descriptor) return null
  const { type, subfolder, filename } = descriptor
  return api.apiURL(
    `/view?type=${type}&subfolder=${encodeURIComponent(subfolder)}&filename=${encodeURIComponent(filename)}&rand=${Date.now()}`
  )
}

function ExampleImages({ img, api }) {
  const beforeSrc = makeImgUrl(api, img.before)
  const afterSrc  = makeImgUrl(api, img.after)
  const hasBefore = !!beforeSrc
  const hasAfter  = !!afterSrc

  if (!hasBefore && !hasAfter) return null

  return (
    <div className="nf-example-row">
      {img.nl_statement && (
        <div className="nf-example-caption">{img.nl_statement}</div>
      )}
      <div className="nf-before-after">
        <div className="nf-ba-pane">
          <span className="nf-ba-label">Before</span>
          {hasBefore ? (
            <img src={beforeSrc} alt="Before" className="nf-ba-img" />
          ) : (
            <div className="nf-ba-placeholder">No image</div>
          )}
        </div>
        <div className="nf-ba-pane">
          <span className="nf-ba-label">After</span>
          {hasAfter ? (
            <img src={afterSrc} alt="After" className="nf-ba-img" />
          ) : (
            <div className="nf-ba-placeholder">No image</div>
          )}
        </div>
      </div>
    </div>
  )
}
