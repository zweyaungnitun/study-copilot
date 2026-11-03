import { useState, type FormEvent, type PointerEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type ScheduledTask, type SessionEnd, type SessionStart } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import TrackCard from '../TrackCard'
import { celebrate } from '../celebrate'
import { Empty, ErrorBox, Icon, Markdown, PageHeader, CountUp, ProgressRing, Segmented, Skeleton, Spinner, useToast, type IconName } from '../ui'

const typeTone: Record<string, string> = { review: 'blue', practice: 'green', learn: '' }
const iso = (d: Date) => d.toISOString().slice(0, 10)
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setUTCDate(x.getUTCDate() + n); return x }
const monday = (d: Date) => { const x = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())); return addDays(x, -((x.getUTCDay() + 6) % 7)) }
const fmtMin = (m: number) => m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}` : ''}` : `${m}m`
const KIND_LABEL: Record<string, string> = { learn: 'Learn', review: 'Review', practice: 'Practice', mock: 'Mock exam', buffer: 'Buffer' }

/** A tutor link that opens the chat with the question typed in (and the chapter in focus, when there is one). */
const tutorHref = (q: string, chapter?: string) => `/tutor?${new URLSearchParams({ q, ...(chapter ? { chapter } : {}) })}`

export default function Dashboard() {
  const { session } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const uid = session!.user_id
  const coach = useLoad(() => api.coach(uid), [uid])
  const road = useLoad(() => api.tracks(uid).catch(() => []), [uid])
  const weekStart = monday(new Date())
  const week = useLoad(() => api.schedule(iso(weekStart), iso(addDays(weekStart, 6))).catch(() => null), [uid])
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
  const [question, setQuestion] = useState('')

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
  const toggleTask = async (t: ScheduledTask) => {
    const status = t.status === 'done' ? 'pending' : 'done'
    const put = (x: ScheduledTask) => week.setData(d => d && { ...d, tasks: d.tasks.map(y => y.id === x.id ? x : y) })
    put({ ...t, status })
    // Finishing the last task of the day deserves a moment.
    if (status === 'done' && todayTasks.every(x => x.id === t.id || x.status === 'done')) { celebrate(); toast('ok', 'Today’s plan is done. Nice work!') }
    try { put(await api.setTask(t.id, status)) } catch (e) { put(t); toast('err', (e as Error).message) }
  }
  // The hero's soft light follows the pointer (CSS reads --mx/--my).
  const spotlight = (e: PointerEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
    e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
  }
  const ask = (e: FormEvent) => { e.preventDefault(); if (question.trim()) navigate(tutorHref(question.trim(), focus?.next?.id)) }

  const needsIntake = coach.error?.includes('profile')
  const st = coach.data?.stats
  const hour = new Date().getHours()
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const todayLabel = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
  const focus = tracks.find(x => x.next)
  const overall = tracks.length ? tracks.reduce((a, x) => a + x.pct, 0) / tracks.length : 0
  const todayIso = iso(new Date())
  const todayTasks = (week.data?.tasks ?? []).filter(t => t.date.slice(0, 10) === todayIso)
  const todayDone = todayTasks.filter(t => t.status === 'done').length
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = addDays(weekStart, i), key = iso(d)
    const ts = (week.data?.tasks ?? []).filter(t => t.date.slice(0, 10) === key)
    const minutes = ts.reduce((a, t) => a + t.minutes, 0)
    const main = ts.find(t => t.kind === 'learn') ?? ts.find(t => t.kind === 'mock') ?? ts[0]
    return {
      key, label: key === todayIso ? 'Today' : d.toLocaleDateString(undefined, { weekday: 'short', timeZone: 'UTC' }), minutes,
      what: main ? (main.kind === 'buffer' ? 'Buffer day' : main.title.replace(/\s*\(part \d+\)$/, '')) : 'Rest',
      state: key === todayIso ? 'today' : ts.length && ts.every(t => t.status === 'done') ? 'done' : key < todayIso && ts.some(t => t.status !== 'done') ? 'missed' : '',
    }
  })
  const mistakes = st?.unresolved_mistakes ?? 0
  const stats: [IconName, string, number, string][] = st ? [
    ['flame', 'peach', st.current_streak, 'day streak'], ['star', 'violet', st.total_xp, 'XP earned'],
    ['clock', 'mint', st.total_minutes, 'minutes studied'], ['alert', 'rose', mistakes, mistakes === 1 ? 'open mistake' : 'open mistakes'],
  ] : []
  const suggestions: [string, string][] = [
    ...(mistakes ? [['Quiz me on my mistakes', 'Quiz me on the mistakes I still have open.'] as [string, string]] : []),
    ...(focus ? [[`Explain ${focus.next!.title.length > 28 ? 'this chapter' : focus.next!.title} simply`, `Explain ${focus.next!.title} simply.`] as [string, string]] : []),
    ['What should I study next?', 'What should I study next, and why?'],
  ]

  if (coach.loading) return <><PageHeader title={`${greet}, ${session!.username}`} /><Skeleton lines={3} /></>
  if (needsIntake) return <><PageHeader title={`${greet}, ${session!.username}`} />
    <Empty icon="target" title="Set up your goal" action={<Link to="/onboarding"><button>Get started <Icon name="arrow" size={16} /></button></Link>}>
      Tell us what you want to learn and by when. We'll build a personalised roadmap.</Empty></>

  return (
    <>
      {coach.error && <ErrorBox>{coach.error}</ErrorBox>}
      <div className="bento stagger">
        <section className="tile tile-hero span-8" aria-label="Next up" onPointerMove={spotlight}>
          <svg className="tile-hero-art" width="300" height="300" viewBox="0 0 300 300" aria-hidden="true">
            <circle cx="150" cy="150" r="128" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 9" />
            <circle cx="150" cy="150" r="84" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <g className="orbit"><circle cx="150" cy="22" r="7" fill="currentColor" /></g>
            <g className="orbit orbit-slow"><circle cx="234" cy="150" r="4.5" fill="currentColor" /></g>
            <circle cx="150" cy="150" r="30" fill="currentColor" opacity="0.5" /></svg>
          <span className="tile-eyebrow">{todayLabel}</span>
          <h1>{greet}, {session!.username}!</h1>
          {focus ? <div className="tile-next">
            <span>{focus.next!.status === 'in_progress' ? 'Continue where you left off' : 'Up next'}</span>
            <b>{focus.next!.title}</b>
            <p>{focus.t.specialization} · about {fmtMin(Math.round(focus.next!.estimated_hours * 60))}</p>
          </div> : <p>{tracks.length ? 'You’ve finished every chapter. Take a mock exam to check what stuck.' : 'Add your textbooks or a docs link, and we’ll turn them into a plan.'}</p>}
          <div className="row">
            {focus ? <Link to={`/chapters/${focus.next!.id}`}><button className="btn-light lg">{focus.next!.status === 'in_progress' ? 'Continue learning' : 'Start learning'}<Icon name="arrow" size={16} /></button></Link>
              : <Link to={tracks.length ? '/exam' : '/library'}><button className="btn-light lg">{tracks.length ? 'Take a mock exam' : 'Add sources'}<Icon name="arrow" size={16} /></button></Link>}
            <Link to={focus ? `/tutor?chapter=${focus.next!.id}` : '/onboarding'}><button className="btn-outline-light lg">{focus ? <><Icon name="chat" size={16} />Ask the tutor</> : 'Set a goal'}</button></Link>
          </div>
        </section>

        <section className="tile span-4 tile-mastery" aria-label="Mastery">
          <ProgressRing value={overall} size={148} stroke={16} label={`Overall mastery ${Math.round(overall)} percent`}>
            <b className="num"><CountUp value={Math.round(overall)} />%</b></ProgressRing>
          <b className="tile-title">{tracks.length === 1 ? tracks[0].t.specialization : tracks.length ? `${tracks.length} tracks` : 'No track yet'}</b>
          <span className="muted">{tracks.length ? `${tracks.reduce((a, x) => a + x.done, 0)} of ${tracks.reduce((a, x) => a + x.total, 0)} chapters done` : 'Mastery grows as you finish chapters'}</span>
        </section>

        <section className="tile span-6" aria-label="Today's plan">
          <div className="tile-head"><h2>Today’s plan</h2>
            {todayTasks.length > 0 ? <span className="muted">{todayDone} of {todayTasks.length} done</span> : <Link to="/schedule" className="tile-link">Schedule</Link>}</div>
          {todayTasks.length ? <ul className="plan">{todayTasks.map(t => (
            <li key={t.id} className={`plan-item kind-${t.kind} ${t.status}`}>
              <label>
                <input type="checkbox" checked={t.status === 'done'} onChange={() => void toggleTask(t)} />
                <span className="grow">{t.chapter_id && t.kind === 'learn' ? <Link to={`/chapters/${t.chapter_id}`}>{t.title}</Link> : t.title}</span>
                <span className="plan-kind">{KIND_LABEL[t.kind] ?? t.kind}</span>
                <span className="plan-min num">{fmtMin(t.minutes)}</span>
              </label>
            </li>))}</ul>
            : <div className="tile-empty"><p className="muted">{week.loading ? 'Loading your plan…' : 'Nothing planned for today.'}</p>
              {!week.loading && <Link to="/schedule"><button className="ghost sm">{week.data?.summary ? 'Open schedule' : 'Build my schedule'}</button></Link>}</div>}
        </section>

        <section className="tile tile-ink span-6" aria-label="Your tutor">
          <div className="tile-head"><span className="tile-badge"><Icon name="spark" size={18} /></span><h2>Your tutor</h2></div>
          <p>{mistakes ? `You have ${mistakes} open mistake${mistakes > 1 ? 's' : ''}. Want a quick check before you move on?` : 'Ask anything. Answers come from your own textbooks, notes and links, with citations.'}</p>
          <div className="tile-chips">{suggestions.map(([label, q]) => (
            <Link key={label} to={tutorHref(q, focus?.next?.id)} className="tile-chip">{label}</Link>))}</div>
          <form className="tile-ask" onSubmit={ask}>
            <input aria-label="Ask the tutor" value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask anything about your notes" />
            <button aria-label="Ask" disabled={!question.trim()}><Icon name="arrow" size={16} /></button>
          </form>
        </section>

        {stats.map(([ic, tone, v, label]) => (
          <div key={label} className={`tile tile-stat span-3 tone-${tone} ${v > 0 ? 'live' : ''}`}>
            <span className="tile-icon"><Icon name={ic} size={18} /></span>
            <b className="num"><CountUp value={v} /></b><span>{label}</span>
          </div>))}

        <section className="tile span-12" aria-label="This week">
          <div className="tile-head"><h2>This week</h2><Link to="/schedule" className="tile-link">Open schedule</Link></div>
          <ol className="week-strip">{days.map(d => (
            <li key={d.key} className={d.state}>
              <span className="week-day">{d.label}{d.state === 'today' && <i className="live-dot" aria-hidden="true" />}</span>
              <b className="num">{d.minutes ? fmtMin(d.minutes) : '–'}</b>
              <span className="week-what">{d.what}</span>
            </li>))}</ol>
        </section>

        {tracks.length > 1 && <section className="tile span-12" aria-label="Your tracks">
          <div className="tile-head"><h2>Your tracks</h2><Link to="/roadmap" className="tile-link">Manage</Link></div>
          <div className="track-grid">{tracks.map(({ t }) => <TrackCard key={t.id} track={t} />)}</div></section>}
        {!road.loading && tracks.length === 0 && <section className="tile span-12">
          <Empty icon="map" title="No roadmap yet" action={<Link to="/onboarding"><button>Build my roadmap</button></Link>}>Your goal is saved, but there's no study plan yet.</Empty></section>}

        <section className="tile span-7" aria-label="Study session">
          <div className="tile-head"><div><h2>Study session</h2><p className="muted">{active ? 'Tick tasks off as you complete them.' : 'Pick your energy level and get a session that fits.'}</p></div></div>
          {!active ? (
            <div className="row" style={{ alignItems: 'center' }}>
              <Segmented label="Energy level" value={energy} onChange={setEnergy} options={[['low', 'Low energy'], ['ok', 'Balanced'], ['high', 'High energy']]} />
              <button onClick={start} disabled={busy}>{busy ? <Spinner /> : <Icon name="arrow" size={16} />}Start session</button>
            </div>
          ) : (
            <>
              <div>{active.tasks.map(t => (
                <label key={t.id} className="choice">
                  <input type="checkbox" checked={done.includes(t.id)} onChange={e => setDone(e.target.checked ? [...done, t.id] : done.filter(x => x !== t.id))} />
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
        </section>
        {coach.data && <section className="tile span-5 tile-coach" aria-label="Weekly coach report">
          <div className="tile-head"><h2>Weekly coach</h2></div><Markdown text={coach.data.report_markdown} /></section>}
      </div>
    </>
  )
}
