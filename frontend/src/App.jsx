import { useState, useEffect, useRef, useCallback } from 'react'
import { api, openRunSocket } from './api.js'

// ── Constants ────────────────────────────────────────────────────────────────

const STATUS_COLOR = {
  passed:      '#00e5a0',
  failed:      '#ff3d6b',
  'self-healed': '#f5a623',
  running:     '#4fc3f7',
  pending:     '#4a5568',
  healed:      '#f5a623',
}
const STATUS_ICON = {
  passed: '✓', failed: '✗', 'self-healed': '⚡', running: '◌', pending: '○', healed: '⚡',
}

// ── Tiny UI primitives ───────────────────────────────────────────────────────

function Spinner({ size = 14, color = '#4fc3f7' }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size,
      border: `2px solid ${color}28`, borderTopColor: color,
      borderRadius: '50%', animation: 'spin .7s linear infinite', flexShrink: 0,
    }} />
  )
}

function Badge({ status }) {
  const c = STATUS_COLOR[status] || '#4a5568'
  return (
    <span style={{
      fontSize: 10, color: c, background: `${c}18`,
      padding: '2px 8px', borderRadius: 20, fontFamily: 'monospace',
      display: 'inline-flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap',
    }}>
      {STATUS_ICON[status] || '○'} {status}
    </span>
  )
}

function Btn({ children, onClick, disabled, variant = 'ghost', style: sx = {}, ...rest }) {
  const variants = {
    ghost:   { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#a0aec0' },
    primary: { background: 'linear-gradient(135deg,#4fc3f7,#00e5a0)', border: 'none', color: '#080b12', fontWeight: 700 },
    green:   { background: 'rgba(0,229,160,0.08)', border: '1px solid rgba(0,229,160,0.25)', color: '#00e5a0' },
    blue:    { background: 'rgba(79,195,247,0.08)', border: '1px solid rgba(79,195,247,0.2)', color: '#4fc3f7' },
    danger:  { background: 'rgba(255,61,107,0.07)', border: '1px solid rgba(255,61,107,0.2)', color: '#ff3d6b' },
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        ...variants[variant],
        padding: '7px 14px', borderRadius: 6, fontSize: 11,
        display: 'inline-flex', alignItems: 'center', gap: 6,
        transition: 'all .18s', opacity: disabled ? .4 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        ...sx,
      }}
      {...rest}
    >
      {children}
    </button>
  )
}

// ── Step row ─────────────────────────────────────────────────────────────────

function StepRow({ step, index, live }) {
  const c = STATUS_COLOR[step.status] || '#4a5568'
  return (
    <div style={{
      display: 'flex', gap: 10, alignItems: 'flex-start',
      padding: '8px 12px', borderRadius: 6, marginBottom: 5,
      background: 'rgba(255,255,255,0.025)',
      borderLeft: `2px solid ${c}`,
      animation: live ? 'fadeUp .25s ease' : 'none',
    }}>
      <span style={{ color: c, fontFamily: 'monospace', fontSize: 11, minWidth: 14, marginTop: 1 }}>
        {live && step.status === 'running' ? <Spinner size={10} color={c} /> : STATUS_ICON[step.status] || '○'}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: '#4fc3f7', background: 'rgba(79,195,247,.1)', padding: '1px 6px', borderRadius: 3, fontFamily: 'monospace' }}>
            {step.action}
          </span>
          <span style={{ fontSize: 11, color: '#a0aec0', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 260 }}>
            {step.target}
          </span>
          {step.value && (
            <span style={{ fontSize: 11, color: '#68d391', fontFamily: 'monospace' }}>→ "{step.value}"</span>
          )}
          {step.duration !== undefined && (
            <span style={{ fontSize: 10, color: '#4a5568', marginLeft: 'auto' }}>{step.duration}s</span>
          )}
        </div>
        {step.heal_note && (
          <div style={{ fontSize: 10, color: '#f5a623', marginTop: 3, fontStyle: 'italic' }}>⚡ Healed: {step.heal_note}</div>
        )}
        {step.error && (
          <div style={{ fontSize: 10, color: '#ff3d6b', marginTop: 3 }}>⚠ {step.error}</div>
        )}
      </div>
    </div>
  )
}

// ── Sidebar test card ─────────────────────────────────────────────────────────

function TestCard({ test, selected, onClick }) {
  return (
    <div onClick={onClick} style={{
      padding: '12px 14px', borderRadius: 7, marginBottom: 6, cursor: 'pointer',
      background: selected ? 'rgba(79,195,247,0.07)' : 'rgba(255,255,255,0.02)',
      border: `1px solid ${selected ? 'rgba(79,195,247,0.35)' : 'rgba(255,255,255,0.05)'}`,
      borderLeft: selected ? '3px solid #4fc3f7' : '3px solid transparent',
      transition: 'all .18s',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
        <div style={{ fontWeight: 600, fontSize: 12, color: '#e2e8f0', lineHeight: 1.4, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {test.name}
        </div>
        <Badge status={test.last_status} />
      </div>
      <div style={{ fontSize: 10, color: '#4a5568', marginTop: 5, display: 'flex', gap: 10 }}>
        <span>⏱ {test.last_duration ? `${test.last_duration}s` : '—'}</span>
        <span>📋 {JSON.parse(test.steps || '[]').length} steps</span>
        {test.self_healed && <span style={{ color: '#f5a623' }}>⚡ healed</span>}
      </div>
    </div>
  )
}

// ── Log line ──────────────────────────────────────────────────────────────────

function LogLine({ entry }) {
  const colors = {
    header: '#4fc3f7', error: '#ff3d6b', success: '#00e5a0',
    heal: '#f5a623', warn: '#f5a623', step: '#a0aec0', info: '#4a5568',
  }
  return (
    <div style={{
      display: 'flex', gap: 12, fontSize: 11, lineHeight: 1.65,
      animation: 'fadeUp .18s ease',
    }}>
      <span style={{ color: '#2d3748', minWidth: 68, flexShrink: 0 }}>{entry.time}</span>
      <span style={{ color: colors[entry.type] || '#a0aec0' }}>{entry.msg}</span>
    </div>
  )
}

// ── Composer panel ────────────────────────────────────────────────────────────

function ComposerPanel({ suites, onTestAdded }) {
  const [suiteId, setSuiteId] = useState(suites[0]?.id || '')
  const [nl, setNl] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (suites.length && !suiteId) setSuiteId(suites[0].id)
  }, [suites])

  const generate = async () => {
    if (!nl.trim()) return
    setLoading(true); setError(''); setPreview(null)
    try {
      const result = await api.generate(nl, baseUrl)
      setPreview(result)
    } catch (e) {
      setError(e.message)
    }
    setLoading(false)
  }

  const addToSuite = async () => {
    if (!preview || !suiteId) return
    setSaving(true)
    try {
      await api.createTest(suiteId, {
        name: preview.name,
        nl_description: nl,
        steps: preview.steps,
        base_url: baseUrl,
      })
      onTestAdded(suiteId)
      setNl(''); setPreview(null); setBaseUrl('')
    } catch (e) {
      setError(e.message)
    }
    setSaving(false)
  }

  const EXAMPLES = [
    'Navigate to https://example.com, check that the page title contains "Example Domain", and verify the "More information" link is visible',
    'Go to https://news.ycombinator.com, wait for the article list to load, click on the first story link, then assert the page title is not empty',
    'Open https://playwright.dev, click the "Get started" button, verify that the installation section is visible on the page',
  ]

  return (
    <div style={{ maxWidth: 700, animation: 'fadeUp .25s ease' }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 20, marginBottom: 6 }}>AI Test Composer</h2>
        <p style={{ color: '#4a5568', fontSize: 12, lineHeight: 1.7 }}>
          Describe your test scenario in plain English. Claude converts it to Playwright steps — no code required.
        </p>
      </div>

      {/* Suite selector */}
      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em', display: 'block', marginBottom: 6 }}>ADD TO SUITE</label>
        <select value={suiteId} onChange={e => setSuiteId(e.target.value)}
          style={{ background: '#0f1520', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0', padding: '8px 12px', borderRadius: 6, fontSize: 12, width: '100%' }}>
          {suites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>

      {/* Base URL */}
      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em', display: 'block', marginBottom: 6 }}>BASE URL (optional)</label>
        <input
          value={baseUrl}
          onChange={e => setBaseUrl(e.target.value)}
          placeholder="https://your-app.com"
          style={{ background: '#0f1520', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0', padding: '8px 12px', borderRadius: 6, fontSize: 12, width: '100%' }}
        />
      </div>

      {/* NL textarea */}
      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em', display: 'block', marginBottom: 6 }}>DESCRIBE YOUR TEST</label>
        <textarea
          value={nl}
          onChange={e => setNl(e.target.value)}
          rows={5}
          placeholder='e.g. "Go to the login page, enter user@example.com and a password, click Sign In, and verify the dashboard heading appears"'
          style={{ width: '100%', background: '#0f1520', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0', padding: '12px 14px', borderRadius: 7, fontSize: 12, lineHeight: 1.7, resize: 'vertical' }}
        />
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 28 }}>
        <Btn variant="primary" onClick={generate} disabled={loading || !nl.trim()} style={{ flex: 1, justifyContent: 'center', padding: '10px 20px', fontSize: 12 }}>
          {loading ? <><Spinner size={13} color="#080b12" /> Generating…</> : '✦ Generate Steps'}
        </Btn>
      </div>

      {error && (
        <div style={{ background: 'rgba(255,61,107,.08)', border: '1px solid rgba(255,61,107,.2)', borderRadius: 7, padding: '10px 14px', fontSize: 12, color: '#ff3d6b', marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Preview */}
      {preview && (
        <div style={{ animation: 'fadeUp .25s ease', marginBottom: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em' }}>GENERATED STEPS</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 3 }}>{preview.name}</div>
            </div>
            <Btn variant="green" onClick={addToSuite} disabled={saving}>
              {saving ? <Spinner size={12} color="#00e5a0" /> : '+ Add to Suite'}
            </Btn>
          </div>
          {preview.steps.map((s, i) => (
            <StepRow key={i} step={{ ...s, status: 'pending' }} index={i} />
          ))}
        </div>
      )}

      {/* Example prompts */}
      {!preview && !loading && (
        <div>
          <div style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em', marginBottom: 10 }}>EXAMPLE PROMPTS</div>
          {EXAMPLES.map((ex, i) => (
            <button key={i} onClick={() => setNl(ex)}
              style={{ width: '100%', textAlign: 'left', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: 6, padding: '10px 14px', fontSize: 11, color: '#718096', lineHeight: 1.6, marginBottom: 7, transition: 'border-color .18s' }}
              onMouseEnter={e => e.currentTarget.style.borderColor = 'rgba(79,195,247,.3)'}
              onMouseLeave={e => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.05)'}>
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Run panel — live WebSocket log ────────────────────────────────────────────

function RunPanel({ runId, liveSteps, logEntries, status }) {
  const logRef = useRef(null)
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logEntries])

  return (
    <div style={{ animation: 'fadeUp .25s ease' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h2 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 20 }}>Live Run Log</h2>
          <p style={{ fontSize: 11, color: '#4a5568', marginTop: 4 }}>Run #{runId}</p>
        </div>
        {status === 'running' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: '#4fc3f7' }}>
            <Spinner /> Executing in browser…
          </div>
        )}
        {status && status !== 'running' && <Badge status={status} />}
      </div>

      {/* Step states */}
      {liveSteps.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em', marginBottom: 8 }}>STEP PROGRESS</div>
          {liveSteps.map((s, i) => <StepRow key={i} step={s} index={i} live />)}
        </div>
      )}

      {/* Raw log */}
      <div style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em', marginBottom: 8 }}>TERMINAL OUTPUT</div>
      <div ref={logRef} style={{
        background: '#060810', border: '1px solid rgba(255,255,255,0.05)', borderRadius: 8,
        padding: '14px 16px', height: 320, overflowY: 'auto', fontFamily: 'monospace',
      }}>
        {logEntries.length === 0
          ? <div style={{ color: '#2d3748', textAlign: 'center', paddingTop: 50, fontSize: 12 }}>Waiting for run to start…</div>
          : logEntries.map((e, i) => <LogLine key={i} entry={e} />)
        }
        {status === 'running' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, fontSize: 11, color: '#4a5568' }}>
            <span style={{ width: 6, height: 6, background: '#4fc3f7', borderRadius: '50%', display: 'inline-block', animation: 'pulse 1s infinite' }} />
            Executing…
          </div>
        )}
      </div>
    </div>
  )
}

// ── Test detail panel ─────────────────────────────────────────────────────────

function TestDetailPanel({ test, onRun, isRunning }) {
  const [runs, setRuns] = useState([])
  const [loadingRuns, setLoadingRuns] = useState(false)
  const steps = JSON.parse(test.steps || '[]')

  useEffect(() => {
    setLoadingRuns(true)
    api.listRuns(test.id).then(r => { setRuns(r); setLoadingRuns(false) }).catch(() => setLoadingRuns(false))
  }, [test.id, isRunning])

  return (
    <div style={{ animation: 'fadeUp .25s ease' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <h2 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 20, marginBottom: 5 }}>{test.name}</h2>
          <div style={{ fontSize: 11, color: '#4a5568', display: 'flex', gap: 12 }}>
            <span>Base URL: {test.base_url || '—'}</span>
            <span>Steps: {steps.length}</span>
            {test.self_healed && <span style={{ color: '#f5a623' }}>⚡ Previously self-healed</span>}
          </div>
        </div>
        <Btn variant="green" onClick={onRun} disabled={isRunning} style={{ fontSize: 12, padding: '8px 18px' }}>
          {isRunning ? <><Spinner size={13} color="#00e5a0" /> Running…</> : '▶ Run Test'}
        </Btn>
      </div>

      {/* NL description */}
      {test.nl_description && (
        <div style={{ background: 'rgba(79,195,247,.05)', border: '1px solid rgba(79,195,247,.12)', borderRadius: 8, padding: '12px 16px', marginBottom: 20 }}>
          <div style={{ fontSize: 9, color: '#4fc3f7', letterSpacing: '.1em', marginBottom: 5 }}>NATURAL LANGUAGE INPUT</div>
          <p style={{ fontSize: 12, color: '#a0aec0', lineHeight: 1.7, fontStyle: 'italic' }}>"{test.nl_description}"</p>
        </div>
      )}

      {/* Status */}
      <div style={{ background: `${STATUS_COLOR[test.last_status] || '#4a5568'}10`, border: `1px solid ${STATUS_COLOR[test.last_status] || '#4a5568'}25`, borderRadius: 8, padding: '10px 16px', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ color: STATUS_COLOR[test.last_status] || '#4a5568', fontSize: 16 }}>{STATUS_ICON[test.last_status] || '○'}</span>
        <span style={{ fontSize: 12, color: STATUS_COLOR[test.last_status] || '#4a5568', fontWeight: 600 }}>
          {test.last_status === 'passed' ? 'All steps passed' :
           test.last_status === 'failed' ? 'Test failed on last run' :
           test.last_status === 'self-healed' ? 'Passed with self-healing — selectors auto-updated' :
           'Not yet run'}
        </span>
      </div>

      {/* Steps */}
      <div style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em', marginBottom: 10 }}>STEPS ({steps.length})</div>
      {steps.map((s, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 4 }}>
          <div style={{ fontSize: 10, color: '#2d3748', minWidth: 22, paddingTop: 10, fontFamily: 'monospace' }}>{String(i + 1).padStart(2, '0')}</div>
          <div style={{ flex: 1 }}><StepRow step={{ ...s, status: 'pending' }} index={i} /></div>
        </div>
      ))}

      {/* Run history */}
      {runs.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <div style={{ fontSize: 10, color: '#4a5568', letterSpacing: '.08em', marginBottom: 10 }}>RUN HISTORY</div>
          {runs.map(r => (
            <div key={r.id} style={{ display: 'flex', gap: 14, alignItems: 'center', padding: '8px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: 6, marginBottom: 5, fontSize: 11 }}>
              <Badge status={r.status} />
              <span style={{ color: '#718096' }}>⏱ {r.duration}s</span>
              <span style={{ color: '#4a5568' }}>{new Date(r.created_at).toLocaleString()}</span>
              {r.screenshot_path && (
                <a href={`http://localhost:8000/${r.screenshot_path}`} target="_blank" rel="noreferrer"
                  style={{ color: '#4fc3f7', fontSize: 10, marginLeft: 'auto' }}>📸 screenshot</a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── New Suite modal ───────────────────────────────────────────────────────────

function NewSuiteModal({ onClose, onCreated }) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!name.trim()) return
    setSaving(true)
    const s = await api.createSuite(name, desc)
    onCreated(s)
    setSaving(false)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 999 }}>
      <div style={{ background: '#0f1520', border: '1px solid rgba(255,255,255,.1)', borderRadius: 12, padding: 28, width: 400 }}>
        <h3 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, marginBottom: 18 }}>New Test Suite</h3>
        <input value={name} onChange={e => setName(e.target.value)} placeholder="Suite name"
          style={{ width: '100%', background: '#080b12', border: '1px solid rgba(255,255,255,.08)', color: '#e2e8f0', padding: '9px 12px', borderRadius: 6, fontSize: 12, marginBottom: 10 }} />
        <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Description (optional)"
          style={{ width: '100%', background: '#080b12', border: '1px solid rgba(255,255,255,.08)', color: '#e2e8f0', padding: '9px 12px', borderRadius: 6, fontSize: 12, marginBottom: 18 }} />
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn variant="primary" onClick={save} disabled={saving || !name.trim()}>
            {saving ? <Spinner size={12} color="#080b12" /> : 'Create'}
          </Btn>
        </div>
      </div>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [suites, setSuites] = useState([])
  const [activeSuite, setActiveSuite] = useState(null)
  const [tests, setTests] = useState([])
  const [selectedTest, setSelectedTest] = useState(null)
  const [activeTab, setActiveTab] = useState('tests')      // tests | composer | run
  const [showNewSuite, setShowNewSuite] = useState(false)

  // Run state
  const [runStatus, setRunStatus] = useState(null)
  const [liveSteps, setLiveSteps] = useState([])
  const [logEntries, setLogEntries] = useState([])
  const [activeRunId, setActiveRunId] = useState(null)
  const wsRef = useRef(null)

  const now = () => new Date().toLocaleTimeString('en-US', { hour12: false })

  // ── Data loading ────────────────────────────────────────────────────────────

  const loadSuites = useCallback(async () => {
    const s = await api.listSuites()
    setSuites(s)
    if (s.length && !activeSuite) setActiveSuite(s[0])
  }, [])

  const loadTests = useCallback(async (suiteId) => {
    const t = await api.listTests(suiteId)
    setTests(t)
    if (t.length && !selectedTest) setSelectedTest(t[0])
  }, [])

  useEffect(() => { loadSuites() }, [])
  useEffect(() => { if (activeSuite) loadTests(activeSuite.id) }, [activeSuite])

  // ── Run a test ──────────────────────────────────────────────────────────────

  const runTest = async (test) => {
    setActiveTab('run')
    setRunStatus('running')
    setLiveSteps(JSON.parse(test.steps || '[]').map(s => ({ ...s, status: 'pending' })))
    setLogEntries([])

    const addLog = (msg, type = 'info') => setLogEntries(p => [...p, { msg, type, time: now() }])
    addLog(`▶ Starting: "${test.name}"`, 'header')

    // Create run + open WebSocket before kicking off
    const run = await api.startRun(test.id)
    setActiveRunId(run.id)

    if (wsRef.current) wsRef.current.close()
    wsRef.current = openRunSocket(run.id, (evt) => {
      if (evt.type === 'step_start') {
        addLog(`[${evt.step + 1}] ${evt.action.toUpperCase()} → ${evt.target}`, 'step')
        setLiveSteps(p => p.map((s, i) => i === evt.step ? { ...s, status: 'running' } : s))
      }
      if (evt.type === 'step_pass') {
        const note = evt.healed ? ` ⚡ Healed: ${evt.heal_note}` : ''
        addLog(`  ✓ OK (${evt.duration}s)${note}`, evt.healed ? 'heal' : 'success')
        setLiveSteps(p => p.map((s, i) => i === evt.step
          ? { ...s, status: evt.healed ? 'healed' : 'passed', heal_note: evt.heal_note, duration: evt.duration }
          : s
        ))
      }
      if (evt.type === 'step_fail') {
        addLog(`  ✗ FAILED (${evt.duration}s): ${evt.error}`, 'error')
        setLiveSteps(p => p.map((s, i) => i === evt.step ? { ...s, status: 'failed', error: evt.error, duration: evt.duration } : s))
      }
      if (evt.type === 'complete') {
        addLog('', 'info')
        addLog(`━━ Complete: ${evt.status.toUpperCase()} in ${evt.duration}s ━━`, 'header')
        setRunStatus(evt.status)
        // Refresh test data (healed selectors may have been saved)
        api.getTest(test.id).then(t => {
          setTests(p => p.map(x => x.id === t.id ? t : x))
          setSelectedTest(t)
        })
      }
    })
  }

  // ── Stats ───────────────────────────────────────────────────────────────────

  const stats = {
    total:  tests.length,
    passed: tests.filter(t => t.last_status === 'passed').length,
    failed: tests.filter(t => t.last_status === 'failed').length,
    healed: tests.filter(t => t.last_status === 'self-healed').length,
    pending: tests.filter(t => t.last_status === 'pending').length,
  }
  const passRate = stats.total > 0 ? Math.round(((stats.passed + stats.healed) / stats.total) * 100) : 0

  const TABS = [['tests', '📋 Steps'], ['composer', '✦ Composer'], ['run', '▶ Run Log']]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#080b12' }}>

      {/* ── Header ── */}
      <header style={{
        height: 54, borderBottom: '1px solid rgba(255,255,255,0.06)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 20px', background: 'rgba(8,11,18,0.98)', flexShrink: 0, zIndex: 100,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 28, height: 28, background: 'linear-gradient(135deg,#4fc3f7,#00e5a0)', borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>⚗</div>
          <div>
            <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 15, letterSpacing: '-.3px' }}>NeuralTest</div>
            <div style={{ fontSize: 9, color: '#2d3748', letterSpacing: '.12em' }}>AI-POWERED WEB TESTING</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {[['✓', stats.passed, '#00e5a0'], ['✗', stats.failed, '#ff3d6b'], ['⚡', stats.healed, '#f5a623']].map(([icon, val, c]) => (
            <div key={icon} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12 }}>
              <span style={{ color: c }}>{icon}</span>
              <span style={{ color: '#a0aec0' }}>{val}</span>
            </div>
          ))}
          <div style={{ width: 1, height: 20, background: 'rgba(255,255,255,.07)' }} />
          <Btn variant="green" onClick={() => selectedTest && runTest(selectedTest)} disabled={runStatus === 'running' || !selectedTest}>
            {runStatus === 'running' ? <><Spinner size={12} color="#00e5a0" /> Running…</> : '▶ Run Selected'}
          </Btn>
        </div>
      </header>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* ── Left sidebar ── */}
        <aside style={{ width: 270, borderRight: '1px solid rgba(255,255,255,0.06)', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>

          {/* Suite picker */}
          <div style={{ padding: '10px 12px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', gap: 8, alignItems: 'center' }}>
            <select value={activeSuite?.id || ''} onChange={e => {
              const s = suites.find(x => x.id === +e.target.value)
              setActiveSuite(s); setSelectedTest(null); setTests([])
            }} style={{ flex: 1, background: '#0f1520', border: '1px solid rgba(255,255,255,.07)', color: '#e2e8f0', padding: '6px 10px', borderRadius: 5, fontSize: 11 }}>
              {suites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              {suites.length === 0 && <option disabled>No suites</option>}
            </select>
            <Btn variant="blue" onClick={() => setShowNewSuite(true)} style={{ padding: '5px 10px', fontSize: 11 }}>+</Btn>
          </div>

          {/* Test list */}
          <div style={{ fontSize: 9, color: '#2d3748', letterSpacing: '.1em', padding: '10px 14px 6px' }}>
            TESTS ({tests.length})
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '0 10px 10px' }}>
            {tests.length === 0 && (
              <div style={{ textAlign: 'center', padding: '30px 14px', fontSize: 11, color: '#2d3748', lineHeight: 1.8 }}>
                No tests yet.<br />
                Use the <span style={{ color: '#4fc3f7' }}>✦ Composer</span> tab<br />to create your first test.
              </div>
            )}
            {tests.map(t => (
              <TestCard key={t.id} test={t} selected={selectedTest?.id === t.id}
                onClick={() => { setSelectedTest(t); setActiveTab('tests') }} />
            ))}
          </div>

          {/* Composer shortcut */}
          <div style={{ padding: 10, borderTop: '1px solid rgba(255,255,255,.05)' }}>
            <Btn variant="blue" onClick={() => setActiveTab('composer')} style={{ width: '100%', justifyContent: 'center', fontSize: 11 }}>
              ✦ New AI Test
            </Btn>
          </div>
        </aside>

        {/* ── Main content ── */}
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

          {/* Tabs */}
          <div style={{ borderBottom: '1px solid rgba(255,255,255,.06)', display: 'flex', padding: '0 20px', flexShrink: 0 }}>
            {TABS.map(([id, label]) => (
              <button key={id} onClick={() => setActiveTab(id)} style={{
                background: 'none', border: 'none', color: activeTab === id ? '#4fc3f7' : '#4a5568',
                padding: '13px 16px', fontSize: 11, letterSpacing: '.05em',
                borderBottom: activeTab === id ? '2px solid #4fc3f7' : '2px solid transparent',
                transition: 'all .18s', cursor: 'pointer',
              }}>
                {label}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: 22 }}>
            {activeTab === 'tests' && selectedTest && (
              <TestDetailPanel test={selectedTest} onRun={() => runTest(selectedTest)} isRunning={runStatus === 'running'} />
            )}
            {activeTab === 'tests' && !selectedTest && (
              <div style={{ textAlign: 'center', paddingTop: 80, color: '#2d3748', fontSize: 13 }}>
                Select a test from the sidebar or create one using the Composer.
              </div>
            )}
            {activeTab === 'composer' && (
              <ComposerPanel suites={suites} onTestAdded={(sid) => { loadTests(sid); setActiveTab('tests') }} />
            )}
            {activeTab === 'run' && (
              <RunPanel runId={activeRunId} liveSteps={liveSteps} logEntries={logEntries} status={runStatus} />
            )}
          </div>
        </main>

        {/* ── Right stats panel ── */}
        <aside style={{ width: 200, borderLeft: '1px solid rgba(255,255,255,.06)', padding: 16, flexShrink: 0, overflowY: 'auto' }}>
          <div style={{ fontSize: 9, color: '#2d3748', letterSpacing: '.1em', marginBottom: 14 }}>OVERVIEW</div>

          {/* Donut */}
          <div style={{ textAlign: 'center', marginBottom: 18 }}>
            <svg width={86} height={86} viewBox="0 0 86 86">
              <circle cx={43} cy={43} r={34} fill="none" stroke="rgba(255,255,255,.04)" strokeWidth={8} />
              {stats.total > 0 && <>
                <circle cx={43} cy={43} r={34} fill="none" stroke="#00e5a0" strokeWidth={8}
                  strokeDasharray={`${(stats.passed / stats.total) * 213.6} 213.6`} strokeDashoffset={53.4} strokeLinecap="round" />
                <circle cx={43} cy={43} r={34} fill="none" stroke="#f5a623" strokeWidth={8}
                  strokeDasharray={`${(stats.healed / stats.total) * 213.6} 213.6`}
                  strokeDashoffset={53.4 - (stats.passed / stats.total) * 213.6} strokeLinecap="round" />
                <circle cx={43} cy={43} r={34} fill="none" stroke="#ff3d6b" strokeWidth={8}
                  strokeDasharray={`${(stats.failed / stats.total) * 213.6} 213.6`}
                  strokeDashoffset={53.4 - ((stats.passed + stats.healed) / stats.total) * 213.6} strokeLinecap="round" />
              </>}
            </svg>
            <div style={{ position: 'relative', marginTop: -62, marginBottom: 14 }}>
              <div style={{ fontSize: 22, fontWeight: 800, fontFamily: "'Syne', sans-serif" }}>{passRate}%</div>
              <div style={{ fontSize: 9, color: '#4a5568' }}>PASS RATE</div>
            </div>
            <div style={{ height: 48 }} />
          </div>

          {[['Passed', stats.passed, '#00e5a0'], ['Self-Healed', stats.healed, '#f5a623'], ['Failed', stats.failed, '#ff3d6b'], ['Pending', stats.pending, '#4a5568']].map(([label, val, c]) => (
            <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid rgba(255,255,255,.03)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                <div style={{ width: 6, height: 6, background: c, borderRadius: '50%' }} />
                <span style={{ fontSize: 11, color: '#718096' }}>{label}</span>
              </div>
              <span style={{ fontSize: 13, fontWeight: 700, color: c }}>{val}</span>
            </div>
          ))}

          <div style={{ marginTop: 22 }}>
            <div style={{ fontSize: 9, color: '#2d3748', letterSpacing: '.1em', marginBottom: 10 }}>ENGINE</div>
            {[['⚡', 'Self-Healing', 'AI repairs broken selectors'], ['🧠', 'NL Authoring', 'Plain English → steps'], ['📸', 'Screenshots', 'Auto-captured on every run'], ['🔌', 'WebSocket', 'Live streaming logs']].map(([icon, name, desc]) => (
              <div key={name} style={{ marginBottom: 10, padding: '9px 10px', background: 'rgba(255,255,255,.02)', borderRadius: 6 }}>
                <div style={{ fontSize: 11, color: '#a0aec0', marginBottom: 2 }}>{icon} {name}</div>
                <div style={{ fontSize: 10, color: '#4a5568' }}>{desc}</div>
              </div>
            ))}
          </div>
        </aside>
      </div>

      {showNewSuite && (
        <NewSuiteModal
          onClose={() => setShowNewSuite(false)}
          onCreated={(s) => {
            setSuites(p => [s, ...p])
            setActiveSuite(s)
            setTests([])
            setSelectedTest(null)
            setShowNewSuite(false)
          }}
        />
      )}
    </div>
  )
}
