import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { admin, utc, type Attempt, type ProctorEvent } from '../api'
import { Empty, ErrorBox, Icon, PageHeader, Segmented, Skeleton, Spinner, useToast } from '../ui'
import { EVENT_LABELS, ReviewBadge, RiskBadge, StatusBadge, ago } from './shared'

type Filter = 'in_progress' | 'needs_review' | 'terminated' | 'all'
const REFRESH_MS = 5000

function AttemptPanel({ id, onChange, onClose }: { id: string; onChange: () => void; onClose: () => void }) {
  const toast = useToast()
  const [data, setData] = useState<{ attempt: Attempt; events: ProctorEvent[] } | null>(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('Please keep your focus on the exam tab.')
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => admin.attempt(id).then(setData).catch(e => setErr(e.message)), [id])
  useEffect(() => {
    void load()
    const t = window.setInterval(() => void load(), REFRESH_MS)
    return () => window.clearInterval(t)
  }, [load])

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try { await fn(); toast('ok', ok); await load(); onChange() } catch (e) { toast('err', (e as Error).message) } finally { setBusy(false) }
  }

  if (err) return <div className="card"><ErrorBox>{err}</ErrorBox></div>
  if (!data) return <Skeleton lines={6} />
  const a = data.attempt
  const running = a.status === 'in_progress'

  return (
    <div className="card proctor-panel">
      <div className="card-head">
        <div><h2>{a.username}</h2><p className="muted">{a.title}</p></div>
        <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={16} /></button>
      </div>
      <div className="row"><StatusBadge a={a} /><RiskBadge risk={a.risk} score={a.integrity_score} /><ReviewBadge a={a} /></div>
      <dl className="facts">
        <div><dt>Started</dt><dd>{utc(a.started_at).toLocaleString()}</dd></div>
        <div><dt>Time limit</dt><dd>{a.time_limit_minutes} min</dd></div>
        <div><dt>Last heartbeat</dt><dd>{ago(a.last_heartbeat_at)}</dd></div>
        <div><dt>Score</dt><dd>{a.score !== null && a.score !== undefined ? `${a.score}/${a.question_count} (${Math.round(a.percentage ?? 0)}%)` : '—'}</dd></div>
      </dl>
      {a.termination_reason && <div className="alert err-box"><Icon name="stop" size={16} />Terminated: {a.termination_reason}</div>}

      {running && (
        <div className="proctor-actions">
          <label htmlFor="warn">Message the student</label>
          <div className="row"><input id="warn" className="grow" value={msg} onChange={e => setMsg(e.target.value)} maxLength={300} />
            <button className="ghost" disabled={busy || !msg.trim()} onClick={() => act(() => admin.warn(a.id, msg.trim()), 'Warning sent')}><Icon name="chat" size={14} />Send warning</button></div>
          <label htmlFor="term">End this exam</label>
          <div className="row"><input id="term" className="grow" value={reason} onChange={e => setReason(e.target.value)} placeholder="Reason shown to the student" maxLength={300} />
            <button className="danger" disabled={busy || !reason.trim()}
              onClick={() => confirm(`Terminate ${a.username}'s exam? This cannot be undone.`) && act(() => admin.terminate(a.id, reason.trim()), 'Exam terminated')}>
              <Icon name="stop" size={14} />Terminate</button></div>
        </div>)}

      {!running && (
        <div className="proctor-actions">
          <label htmlFor="note">Review {a.review_verdict && <span className="hint">· currently {a.review_verdict}</span>}</label>
          <textarea id="note" rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder={a.review_note || 'Optional note for the record'} maxLength={1000} />
          <div className="row">
            <button className="ghost" disabled={busy} onClick={() => act(() => admin.review(a.id, 'cleared', note || undefined), 'Marked as cleared')}><Icon name="check" size={14} />Clear</button>
            <button className="danger" disabled={busy} onClick={() => act(() => admin.review(a.id, 'confirmed', note || undefined), 'Violation confirmed')}><Icon name="alert" size={14} />Confirm violation</button>
            {busy && <Spinner />}
          </div>
        </div>)}

      <h3 className="section-title" style={{ marginTop: 20 }}>Timeline</h3>
      <ol className="timeline">{data.events.length === 0 && <li className="muted">No events yet.</li>}
        {data.events.slice().reverse().map(e => {
          const [label, icon] = EVENT_LABELS[e.type] ?? [e.type, 'alert']
          return <li key={e.id} className={e.weight ? 'flag' : ''}>
            <span className="tl-icon"><Icon name={icon} size={14} /></span>
            <div className="grow"><b>{label}</b>{e.detail && <div className="muted">{e.detail}</div>}</div>
            <div className="tl-meta">{e.weight > 0 && <span className="badge red num">−{e.weight}</span>}<span className="muted num">{utc(e.created_at).toLocaleTimeString()}</span></div>
          </li>
        })}</ol>
    </div>
  )
}

export default function AdminProctoring() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('attempt')
  const [filter, setFilter] = useState<Filter>('in_progress')
  const [rows, setRows] = useState<Attempt[] | null>(null)
  const [err, setErr] = useState('')

  const load = useCallback(() => admin.attempts(filter === 'all' ? undefined : filter).then(r => { setRows(r); setErr('') })
    .catch(e => setErr(e.message)), [filter])
  useEffect(() => {
    setRows(null); void load()
    if (filter !== 'in_progress') return
    const t = window.setInterval(() => void load(), REFRESH_MS)  // live view keeps itself current
    return () => window.clearInterval(t)
  }, [load, filter])

  const select = (id: string | null) => setParams(id ? { attempt: id } : {})

  return (
    <>
      <PageHeader title="Proctoring" sub="Watch running exams, warn or stop students, and review flagged attempts."
        actions={<Segmented label="Filter" value={filter} onChange={setFilter}
          options={[['in_progress', 'Running'], ['needs_review', 'Needs review'], ['terminated', 'Terminated'], ['all', 'All']]} />} />
      {err && <ErrorBox>{err}</ErrorBox>}
      <div className={`proctor-layout ${selected ? 'has-panel' : ''}`}>
        <div>
          {!rows ? <Skeleton lines={5} /> : !rows.length
            ? <Empty icon="shield" title={filter === 'in_progress' ? 'No exams running' : 'Nothing here'}>
              {filter === 'in_progress' ? 'Running exams appear here live, refreshed every few seconds.' : 'No attempts match this filter.'}</Empty>
            : <div className="card table-card"><table className="table">
              <thead><tr><th>Student</th><th>Status</th><th>Integrity</th><th className="r">Flags</th><th>Started</th><th className="r">Score</th></tr></thead>
              <tbody>{rows.map(a => (
                <tr key={a.id} className={`clickable ${selected === a.id ? 'on' : ''}`} onClick={() => select(a.id)}
                  tabIndex={0} onKeyDown={e => e.key === 'Enter' && select(a.id)}>
                  <td><b>{a.username}</b><div className="muted">{a.question_count} q · {a.time_limit_minutes} min</div></td>
                  <td><StatusBadge a={a} /> <ReviewBadge a={a} /></td>
                  <td><RiskBadge risk={a.risk} score={a.integrity_score} /></td>
                  <td className="r num">{a.flag_count}</td>
                  <td className="muted">{ago(a.started_at)}</td>
                  <td className="r num">{a.percentage !== null && a.percentage !== undefined ? `${Math.round(a.percentage)}%` : '—'}</td>
                </tr>))}</tbody></table></div>}
        </div>
        {selected && <AttemptPanel key={selected} id={selected} onChange={() => void load()} onClose={() => select(null)} />}
      </div>
    </>
  )
}
