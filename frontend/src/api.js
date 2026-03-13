const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function req(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // AI
  generate:     (description, url)     => req('POST', '/generate', { description, url }),

  // Suites
  listSuites:   ()                     => req('GET',  '/suites'),
  createSuite:  (name, description)    => req('POST', '/suites', { name, description }),
  deleteSuite:  (id)                   => req('DELETE', `/suites/${id}`),

  // Tests
  listTests:    (suiteId)              => req('GET',  `/suites/${suiteId}/tests`),
  createTest:   (suiteId, payload)     => req('POST', `/suites/${suiteId}/tests`, payload),
  getTest:      (id)                   => req('GET',  `/tests/${id}`),
  deleteTest:   (id)                   => req('DELETE', `/tests/${id}`),

  // Runs
  startRun:     (testId)               => req('POST', `/tests/${testId}/run`),
  listRuns:     (testId)               => req('GET',  `/tests/${testId}/runs`),
  getRun:       (runId)                => req('GET',  `/runs/${runId}`),
}

export function openRunSocket(runId, onEvent) {
  const wsBase = BASE.replace(/^http/, 'ws')
  const ws = new WebSocket(`${wsBase}/ws/${runId}`)
  ws.onmessage = (e) => onEvent(JSON.parse(e.data))
  ws.onerror   = (e) => console.error('WS error', e)
  return ws
}
