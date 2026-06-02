import { useState, useEffect, useRef, useCallback } from 'react'
import { IdleView } from './components/IdleView.jsx'
import { PrecheckingView } from './components/PrecheckingView.jsx'
import { RetrievalResultView } from './components/RetrievalResultView.jsx'
import { AuthoringView } from './components/AuthoringView.jsx'
import { ConfirmView } from './components/ConfirmView.jsx'
import { AmbiguityView } from './components/AmbiguityView.jsx'
import { ApprovalView } from './components/ApprovalView.jsx'
import { TerminalView } from './components/TerminalView.jsx'
import { Header } from './components/Header.jsx'

const JOB_KEY = 'nodeforge__job_id'
const TERMINAL_STATES = new Set(['banked', 'rejected', 'error', 'exists', 'cancelled'])

export function App({ api }) {
  const [view, setView] = useState('idle')    // idle | prechecking | retrieval-result | authoring | confirm | ambiguity | approval | terminal
  const [ask, setAsk] = useState('')
  const [jobId, setJobId] = useState(null)
  const [log, setLog] = useState([])
  const [precheck, setPrecheck] = useState(null)       // { band, hit, candidates }
  const [confirmData, setConfirmData] = useState(null) // await_confirm payload
  const [ambiguityData, setAmbiguityData] = useState(null) // await_ambiguity payload
  const [approvalData, setApprovalData] = useState(null)   // await_approval payload
  const [terminalData, setTerminalData] = useState(null)   // banked/rejected/error/exists/cancelled payload + type

  // Model/n state (advanced)
  const [model, setModel] = useState('claude-sonnet-4-6')
  const [n, setN] = useState(3)

  const currentJobIdRef = useRef(null)
  const listenersBound = useRef(false)

  // ── Event dispatch logic ───────────────────────────────────────────────────
  const handleEvent = useCallback((eventName, payload) => {
    // Filter by job
    if (currentJobIdRef.current && payload.job_id && payload.job_id !== currentJobIdRef.current) return

    switch (eventName) {
      case 'nodeforge:stage':
        setLog(prev => [...prev, payload.line])
        break
      case 'nodeforge:await_confirm':
        setConfirmData(payload)
        setView('confirm')
        break
      case 'nodeforge:await_ambiguity':
        setAmbiguityData(payload)
        setView('ambiguity')
        break
      case 'nodeforge:await_approval':
        setApprovalData(payload)
        setView('approval')
        break
      case 'nodeforge:banked':
        setTerminalData({ type: 'banked', ...payload })
        setView('terminal')
        clearJob()
        break
      case 'nodeforge:rejected':
        setTerminalData({ type: 'rejected', ...payload })
        setView('terminal')
        clearJob()
        break
      case 'nodeforge:error':
        setTerminalData({ type: 'error', ...payload })
        setView('terminal')
        clearJob()
        break
      case 'nodeforge:exists':
        setTerminalData({ type: 'exists', ...payload })
        setView('terminal')
        clearJob()
        break
      case 'nodeforge:cancelled':
        setTerminalData({ type: 'cancelled', ...payload })
        setView('terminal')
        clearJob()
        break
      case 'nodeforge:restarting':
        // handle in terminal view
        break
    }
  }, [])

  // ── Bind WS listeners once on mount ────────────────────────────────────────
  useEffect(() => {
    if (listenersBound.current) return
    listenersBound.current = true

    const EVENTS = [
      'nodeforge:stage',
      'nodeforge:await_confirm',
      'nodeforge:await_ambiguity',
      'nodeforge:await_approval',
      'nodeforge:banked',
      'nodeforge:rejected',
      'nodeforge:error',
      'nodeforge:exists',
      'nodeforge:cancelled',
      'nodeforge:restarting',
    ]

    const handlers = {}
    EVENTS.forEach(evt => {
      handlers[evt] = (e) => handleEvent(evt, e.detail)
      api.addEventListener(evt, handlers[evt])
    })

    return () => {
      EVENTS.forEach(evt => api.removeEventListener(evt, handlers[evt]))
    }
  }, [api, handleEvent])

  // ── Resume from localStorage on mount ─────────────────────────────────────
  useEffect(() => {
    const storedJobId = localStorage.getItem(JOB_KEY)
    if (!storedJobId) return

    api.fetchApi(`/nodeforge/jobs/${storedJobId}`)
      .then(r => r.json())
      .then(data => {
        if (!data.job_id || TERMINAL_STATES.has(data.status)) {
          localStorage.removeItem(JOB_KEY)
          return
        }
        // Restore job
        setJobId(data.job_id)
        currentJobIdRef.current = data.job_id
        setAsk(data.ask || '')
        setLog(data.log || [])

        // Re-dispatch last event to restore view
        if (data.last_event) {
          const [evtName, payload] = data.last_event
          // Temporarily allow any job_id for the re-dispatch
          handleEvent(evtName, { ...payload, job_id: data.job_id })
        } else {
          setView('authoring')
        }
      })
      .catch(() => {
        localStorage.removeItem(JOB_KEY)
      })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Helpers ────────────────────────────────────────────────────────────────
  function clearJob() {
    localStorage.removeItem(JOB_KEY)
  }

  function storeJob(id) {
    localStorage.setItem(JOB_KEY, id)
  }

  function startOver() {
    // Cancel job if active
    if (jobId) {
      api.fetchApi(`/nodeforge/jobs/${jobId}`, { method: 'DELETE' }).catch(() => {})
      clearJob()
    }
    currentJobIdRef.current = null
    setJobId(null)
    setLog([])
    setPrecheck(null)
    setConfirmData(null)
    setAmbiguityData(null)
    setApprovalData(null)
    setTerminalData(null)
    setView('idle')
  }

  // ── Submit ask → precheck ──────────────────────────────────────────────────
  async function handleSubmit(askText) {
    setAsk(askText)
    setView('prechecking')
    try {
      const res = await api.fetchApi('/nodeforge/precheck', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ask: askText, model }),
      })
      const data = await res.json()
      setPrecheck(data)

      if (data.band === 'low') {
        // Skip retrieval card — go straight to job
        await createJob(askText)
      } else {
        setView('retrieval-result')
      }
    } catch (err) {
      setTerminalData({ type: 'error', detail: `Precheck failed: ${err.message}` })
      setView('terminal')
    }
  }

  // ── Create job ─────────────────────────────────────────────────────────────
  async function createJob(askText) {
    try {
      setLog([])
      setView('authoring')
      const res = await api.fetchApi('/nodeforge/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ask: askText, n, model, clientId: api.clientId }),
      })
      const data = await res.json()
      setJobId(data.job_id)
      currentJobIdRef.current = data.job_id
      storeJob(data.job_id)
    } catch (err) {
      setTerminalData({ type: 'error', detail: `Failed to create job: ${err.message}` })
      setView('terminal')
    }
  }

  // ── Confirm ────────────────────────────────────────────────────────────────
  async function handleConfirm({ drop, add_invariants }) {
    await api.fetchApi(`/nodeforge/jobs/${jobId}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ drop, add_invariants }),
    })
    setView('authoring')
  }

  // ── Ambiguity ──────────────────────────────────────────────────────────────
  async function handleAmbiguity(choice) {
    await api.fetchApi(`/nodeforge/jobs/${jobId}/ambiguity`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ choice }),
    })
    setView('authoring')
  }

  // ── Approve/reject ─────────────────────────────────────────────────────────
  async function handleApprove(decision, reason) {
    const body = { decision }
    if (reason) body.reason = reason
    await api.fetchApi(`/nodeforge/jobs/${jobId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  }

  // ── Restart ────────────────────────────────────────────────────────────────
  async function handleRestart() {
    if (!jobId) return
    await api.fetchApi(`/nodeforge/jobs/${jobId}/restart`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    setTimeout(() => location.reload(), 3000)
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  const isActive = view !== 'idle' && view !== 'terminal'

  return (
    <div className="nf-root">
      <Header
        onStartOver={startOver}
        canCancel={isActive}
        jobId={jobId}
      />

      <div className="nf-body">
        {view === 'idle' && (
          <IdleView
            onSubmit={handleSubmit}
            model={model}
            setModel={setModel}
            n={n}
            setN={setN}
          />
        )}

        {view === 'prechecking' && (
          <PrecheckingView ask={ask} />
        )}

        {view === 'retrieval-result' && (
          <RetrievalResultView
            precheck={precheck}
            ask={ask}
            onAuthorAnyway={() => createJob(ask)}
            onUseIt={startOver}
          />
        )}

        {view === 'authoring' && (
          <AuthoringView log={log} />
        )}

        {view === 'confirm' && confirmData && (
          <ConfirmView
            data={confirmData}
            api={api}
            onConfirm={handleConfirm}
          />
        )}

        {view === 'ambiguity' && ambiguityData && (
          <AmbiguityView
            data={ambiguityData}
            onChoose={handleAmbiguity}
          />
        )}

        {view === 'approval' && approvalData && (
          <ApprovalView
            data={approvalData}
            api={api}
            onApprove={handleApprove}
            onReject={(reason) => handleApprove('reject', reason)}
          />
        )}

        {view === 'terminal' && terminalData && (
          <TerminalView
            data={terminalData}
            onStartOver={startOver}
            onRestart={handleRestart}
          />
        )}
      </div>
    </div>
  )
}
