import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type SessionEnd, type SessionStart } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import TrackCard from '../TrackCard'
import { Empty, ErrorBox, Icon, Markdown, PageHeader, CountUp, ProgressRing, Segmented, Skeleton, Spinner, useToast, type IconName } from '../ui'

const typeTone: Record<string, string> = { review: 'yellow', practice: 'green', learn: '' }

export default function Dashboard() {
  const { session } = useAuth()
  const toast = useToast()
  const uid = session!.user_id
  const coach = useLoad(() => api.coach(uid), [uid])
  const road = useLoad(() => api.tracks(uid).catch(() => []), [uid])
  const tracks = (road.data ?? []).map(t => {
    const cs = t.subjects.flatMap(s => s.chapters)
    return { t, next: cs.find(c => c.status === 'in_progress') ?? cs.find(c => c.status === 'unlocked'), pct: cs.length ? cs.reduce((a, c) => a + c.mastery_score, 0) / cs.length : 0, done: cs.filter(c => c.status === 'completed').length, total: cs.length }
  })
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
  const st = coach.data?.stats
  const hour = new Date().getHours()
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
  const focus = tracks.find(x => x.next)
  const overall = tracks.length ? tracks.reduce((a, x) => a + x.pct, 0) / tracks.length : 0
  const chips: [IconName, string, string | number, string][] = st ? [
    ['flame', 'orange', st.current_streak, 'day streak'], ['star', 'spark', st.total_xp, 'XP'],
    ['clock', 'green', st.total_minutes, 'min studied'], ['alert', 'red', st.unresolved_mistakes, 'open mistakes'],
  ] : []

  return (
    <>
      {coach.loading && <><PageHeader title={`${greet}, ${session!.username}`} /><Skeleton lines={3} /></>}
      {needsIntake && <><PageHeader title={`${greet}, ${session!.username}`} /><Empty icon="target" title="Set up your goal" action={<Link to="/onboarding"><button>Get started <Icon name="arrow" size={16} /></button></Link>}>
        Tell us what you want to learn and by when. We'll build a personalised roadmap.</Empty></>}
      {st && (
        <section className="hero" aria-label="Today">
          <div className="hero-main">
            <span className="hero-eyebrow">{today}</span>
            <h1>{greet}, <span className="grad-text">{session!.username}</span></h1>
            <p className="hero-sub">{focus ? <>Pick up where you left off in <b>{focus.t.specialization}</b>.</> : tracks.length ? 'You\'ve finished every chapter. Take a mock exam to check what stuck.' : 'Create your first track to get a personalised plan.'}</p>
            <div className="row hero-actions">
              {focus ? <Link to={`/chapters/${focus.next!.id}`}><button className="lg">{focus.next!.status === 'in_progress' ? 'Continue' : 'Start'}: {focus.next!.title} <Icon name="arrow" size={16} /></button></Link>
                : <Link to={tracks.length ? '/exam' : '/onboarding'}><button className="lg">{tracks.length ? 'Take a mock exam' : 'Build my roadmap'} <Icon name="arrow" size={16} /></button></Link>}
              {focus && <Link to={`/tutor?chapter=${focus.next!.id}`}><button className="ghost lg"><Icon name="chat" size={16} />Ask tutor</button></Link>}
            </div>
          </div>
          <div className="hero-side">
            {tracks.length > 0 && <div className="hero-ring"><ProgressRing value={overall} size={96} stroke={9} tone="spark" label={`Overall mastery ${Math.round(overall)} percent`}>
              <b className="num"><CountUp value={Math.round(overall)} />%</b></ProgressRing><span className="muted">Overall mastery</span></div>}
            <div className="hero-chips">{chips.map(([ic, tone, v, l]) => (
              <div className="hero-chip" key={l}><span className={`stat-icon ${tone}`}><Icon name={ic} size={16} /></span><b className="num"><CountUp value={Number(v)} /></b><span className="muted">{l}</span></div>))}</div>
          </div>
        </section>)}

      {!needsIntake && !coach.loading && tracks.length > 0 && (
        <div className="card">
          <div className="card-head"><h2>{tracks.length > 1 ? 'Your tracks' : 'Continue learning'}</h2><Link to="/roadmap" className="muted">Manage</Link></div>
          <div className="track-grid stagger">{tracks.map(({ t }) => <TrackCard key={t.id} track={t} />)}</div></div>)}
      {!needsIntake && !coach.loading && !road.loading && tracks.length === 0 && (
        <Empty icon="map" title="No roadmap yet" action={<Link to="/onboarding"><button>Build my roadmap</button></Link>}>Your goal is saved, but there's no study plan yet.</Empty>)}

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
