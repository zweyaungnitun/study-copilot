import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type SessionEnd, type SessionStart } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Empty, ErrorBox, Icon, Markdown, PageHeader, Segmented, Skeleton, Spinner, useToast, type IconName } from '../ui'

const typeTone: Record<string, string> = { review: 'yellow', practice: 'green', learn: '' }

export default function Dashboard() {
  const { session } = useAuth()
  const toast = useToast()
  const uid = session!.user_id
  const coach = useLoad(() => api.coach(uid), [uid])
  const [energy, setEnergy] = useState('ok')
  const [active, setActive] = useState<SessionStart | null>(null)
  const [startedAt, setStartedAt] = useState(0)
  const [done, setDone] = useState<string[]>([])
  const [summary, setSummary] = useState<SessionEnd | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const start = async () => {
    setErr(''); setSummary(null); setBusy(true)
    try { setActive(await api.startSession(uid, energy)); setStartedAt(Date.now()); setDone([]) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const end = async () => {
    if (!active) return
    setBusy(true)
    try {
      const mins = Math.max(1, Math.round((Date.now() - startedAt) / 60000))
      const r = await api.endSession({ session_id: active.session_id, duration_minutes: mins, completed_task_ids: done })
      setSummary(r); setActive(null); toast('ok', `+${r.xp_earned} XP earned`); coach.setData(await api.coach(uid))
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const needsIntake = coach.error?.includes('profile')
  const s = coach.data?.stats
  const tiles: [IconName, string, string | number, string, string][] = s ? [
    ['flame', 'orange', s.current_streak, 'Day streak', ''], ['star', '', s.total_xp, 'Total XP', ''],
    ['clock', 'green', s.total_minutes, 'Minutes studied', ''], ['alert', 'red', s.unresolved_mistakes, 'Open mistakes', ''],
  ] : []
  const hour = new Date().getHours()
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

  return (
    <>
      <PageHeader title={`${greet}, ${session!.username}`} sub="Here's your progress and today's plan." />
      {coach.loading && <Skeleton lines={3} />}
      {needsIntake && <Empty icon="target" title="Set up your goal" action={<Link to="/onboarding"><button>Get started <Icon name="arrow" size={16} /></button></Link>}>
        Tell us what you want to learn and by when. We'll build a personalised roadmap.</Empty>}
      {s && <div className="stats">{tiles.map(([ic, tone, v, l]) => (
        <div className="card" key={l}><span className={`stat-icon ${tone}`}><Icon name={ic} size={20} /></span>
          <div><div className="stat">{v}</div><div className="stat-label">{l}</div></div></div>))}</div>}

      {!needsIntake && !coach.loading && (
        <div className="cols">
          <div className="card">
            <div className="card-head"><div><h2>Study session</h2><p className="muted">{active ? 'Tick tasks off as you complete them.' : 'Pick your energy level and get a tailored plan.'}</p></div></div>
            {!active ? (
              <>
                <Segmented label="Energy level" value={energy} onChange={setEnergy} options={[['low', '😴 Low'], ['ok', '🙂 Balanced'], ['high', '⚡ High']]} />
                <div style={{ marginTop: 18 }}><button className="lg" onClick={start} disabled={busy}>{busy ? <Spinner /> : <Icon name="arrow" size={16} />}Start session</button></div>
              </>
            ) : (
              <>
                <div>{active.tasks.map(t => (
                  <label key={t.id} className="choice">
                    <input type="checkbox" checked={done.includes(t.id)}
                      onChange={e => setDone(e.target.checked ? [...done, t.id] : done.filter(x => x !== t.id))} />
                    <span className="grow">{t.title}</span>
                    <span className={`badge ${typeTone[t.type] ?? 'gray'}`}>{t.estimated_minutes} min · {t.type}</span>
                  </label>))}</div>
                <div className="row" style={{ marginTop: 18 }}>
                  <button onClick={end} disabled={busy}>{busy && <Spinner />}Finish session</button>
                  <span className="muted">{done.length}/{active.tasks.length} done</span></div>
              </>
            )}
            {summary && <div className="alert ok-box"><Icon name="check" size={16} /><span>{summary.message} <b>+{summary.xp_earned} XP</b> · streak {summary.streak_updated} days</span></div>}
            {err && <ErrorBox>{err}</ErrorBox>}
          </div>
          {coach.data && <div className="card"><div className="card-head"><h2>Weekly coach report</h2></div><Markdown text={coach.data.report_markdown} /></div>}
        </div>)}
      {coach.error && !needsIntake && <ErrorBox>{coach.error}</ErrorBox>}
    </>
  )
}
