import React, { useEffect, useState } from 'react'

const API = '/api'

function App() {
  const [metrics, setMetrics] = useState(null)
  const [events, setEvents] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchData = async () => {
    try {
      const [mRes, eRes] = await Promise.all([
        fetch(`${API}/metrics`),
        fetch(`${API}/events?limit=50`),
      ])
      if (!mRes.ok || !eRes.ok) throw new Error('API request failed')
      setMetrics(await mRes.json())
      setEvents(await eRes.json())
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [])

  const handleAction = async (eventId, action) => {
    try {
      await fetch(`${API}/events/${eventId}/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, comment: `Dashboard ${action}` }),
      })
      fetchData()
    } catch (err) {
      alert('Action failed: ' + err.message)
    }
  }

  if (loading) return <div className="app loading">Loading DriftGuard…</div>
  if (error) return (
    <div className="app error">
      <p>⚠️ {error}</p>
      <p style={{ fontSize: '0.85rem', marginTop: 8 }}>
        Make sure the API is running: <code>uvicorn driftguard.api:app --reload</code>
      </p>
    </div>
  )

  return (
    <div className="app">
      {/* Header */}
      <header>
        <h1>🛡️ <span>Drift</span>Guard</h1>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          Infrastructure Drift Detection & Reconciliation
        </span>
      </header>

      {/* KPI tiles */}
      {metrics && (
        <div className="kpi-grid">
          <div className="kpi blue">
            <div className="value">{metrics.total}</div>
            <div className="label">Total Events</div>
          </div>
          <div className="kpi green">
            <div className="value">{metrics.reconciled}</div>
            <div className="label">Reconciled</div>
          </div>
          <div className="kpi orange">
            <div className="value">{metrics.pending}</div>
            <div className="label">Pending</div>
          </div>
          <div className="kpi red">
            <div className="value">{metrics.failed}</div>
            <div className="label">Failed</div>
          </div>
        </div>
      )}

      {/* Events table */}
      <p className="section-title">Drift Events</p>
      {events.length === 0 ? (
        <div className="loading">No drift events recorded yet. Run the pipeline to detect drift.</div>
      ) : (
        <table className="events-table">
          <thead>
            <tr>
              <th>Resource</th>
              <th>Type</th>
              <th>Env</th>
              <th>Classification</th>
              <th>Risk</th>
              <th>Decision</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {events.map(ev => (
              <tr key={ev.id}>
                <td>
                  <a href="#" onClick={e => { e.preventDefault(); setSelected(ev) }}
                     style={{ color: 'var(--accent)', textDecoration: 'none' }}>
                    {ev.terraform_address}
                  </a>
                </td>
                <td>{ev.resource_type}</td>
                <td>{ev.env}</td>
                <td>{ev.classification}</td>
                <td>{ev.risk_score}</td>
                <td>{ev.decision}</td>
                <td><span className={`badge ${ev.status}`}>{ev.status}</span></td>
                <td>
                  {(ev.status === 'detected' || ev.status === 'pending') && (
                    <>
                      <button className="btn btn-reconcile" onClick={() => handleAction(ev.id, 'reconcile')}>
                        Reconcile
                      </button>
                      <button className="btn btn-ignore" onClick={() => handleAction(ev.id, 'ignore')}>
                        Ignore
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Detail modal */}
      {selected && (
        <div className="modal-overlay" onClick={() => setSelected(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <button className="close" onClick={() => setSelected(null)}>✕</button>
            <h2>{selected.terraform_address}</h2>
            <p><strong>Type:</strong> {selected.resource_type}</p>
            <p><strong>Env:</strong> {selected.env}</p>
            <p><strong>Classification:</strong> {selected.classification} (risk: {selected.risk_score})</p>
            <p><strong>Decision:</strong> {selected.decision}</p>
            <p><strong>Status:</strong> <span className={`badge ${selected.status}`}>{selected.status}</span></p>
            <p><strong>Actions:</strong> {JSON.stringify(selected.actions)}</p>
            <p><strong>Timestamp:</strong> {selected.timestamp}</p>
            {selected.diff_summary && (
              <>
                <p style={{ marginTop: 12 }}><strong>Diff:</strong></p>
                <pre>{selected.diff_summary}</pre>
              </>
            )}
            {selected.reconciler_output && (
              <>
                <p style={{ marginTop: 12 }}><strong>Reconciler Output:</strong></p>
                <pre>{selected.reconciler_output}</pre>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default App
