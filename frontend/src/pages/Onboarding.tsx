import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type DiagQ, type DiagResult } from '../api'
import { useAuth } from '../auth'
import { ErrorBox, Icon, PageHeader, Spinner } from '../ui'

export default function Onboarding() {
  const { session } = useAuth()
  const nav = useNavigate()
  const uid = session!.user_id
  const [f, setF] = useState({ goal: '', deadline: '', hours_per_day: 1, level: 'beginner', preferred_study_time: 'evening' })
  const [quiz, setQuiz] = useState<DiagQ[] | null>(null)
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [result, setResult] = useState<DiagResult | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async (fn: () => Promise<void>) => {
    setErr(''); setBusy(true)
    try { await fn() } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  const saveProfile = (e: FormEvent) => { e.preventDefault(); run(async () => {
    await api.saveProfile({ ...f, user_id: uid, deadline: new Date(f.deadline).toISOString(), hours_per_day: Number(f.hours_per_day) })
    setQuiz(await api.diagnostic(f.goal, f.level))
  }) }
  const submitQuiz = () => run(async () => {
    setResult(await api.submitDiagnostic(uid, f.goal, Object.entries(answers).map(([question_id, selected_option_index]) => ({ question_id, selected_option_index }))))
  })
  const build = () => run(async () => { await api.generateRoadmap(uid); nav('/roadmap') })
  const step = result ? 3 : quiz ? 2 : 1
  const steps = <div className="steps" aria-label={`Step ${step} of 3`}>{[1, 2, 3].map(n => <div key={n} className={n <= step ? 'done' : ''} />)}</div>
  const today = new Date().toISOString().slice(0, 10)

  if (result) return (
    <div className="narrow">{steps}
      <PageHeader title={`You're at ${result.calibrated_level} level`} sub={`Diagnostic score: ${Math.round(result.score_percentage)}%`} />
      <div className="card"><h2>Recommended focus</h2><p>{result.recommended_focus}</p>
        {result.identified_weaknesses.length > 0 && <div className="row" style={{ marginTop: 12 }}>{result.identified_weaknesses.map(w => <span key={w} className="badge yellow">{w}</span>)}</div>}</div>
      {err && <ErrorBox>{err}</ErrorBox>}
      <button className="lg" disabled={busy} onClick={build}>{busy ? <Spinner /> : <Icon name="map" size={16} />}{busy ? 'Building your roadmap…' : 'Generate my roadmap'}</button>
    </div>)
  if (quiz) return (
    <div className="narrow">{steps}
      <PageHeader title="Quick diagnostic" sub={`${Object.keys(answers).length} of ${quiz.length} answered — this helps us calibrate your plan.`} />
      {quiz.map((q, n) => (
        <div className="card" key={q.id}><h2><span className="muted">{n + 1}.</span> {q.question}</h2>
          {q.options.map((o, i) => (
            <label key={i} className="choice"><input type="radio" name={q.id} checked={answers[q.id] === i} onChange={() => setAnswers({ ...answers, [q.id]: i })} />{o}</label>))}
        </div>))}
      {err && <ErrorBox>{err}</ErrorBox>}
      <div className="row"><button className="lg" disabled={busy || Object.keys(answers).length < quiz.length} onClick={submitQuiz}>{busy && <Spinner />}Submit</button>
        <button className="ghost lg" disabled={busy} onClick={build}>Skip for now</button></div>
    </div>)
  return (
    <div className="narrow">{steps}
      <PageHeader title="Set your goal" sub="Tell us what you're aiming for and we'll plan the route." />
      <form className="card" onSubmit={saveProfile}>
        <label htmlFor="goal" style={{ marginTop: 0 }}>What do you want to learn?</label>
        <input id="goal" value={f.goal} placeholder="e.g. Organic chemistry, Data structures" onChange={e => setF({ ...f, goal: e.target.value })} minLength={3} required />
        <div className="form-grid">
          <div><label htmlFor="dl">Deadline</label><input id="dl" type="date" min={today} value={f.deadline} onChange={e => setF({ ...f, deadline: e.target.value })} required /></div>
          <div><label htmlFor="hpd">Hours per day</label><input id="hpd" type="number" min={0.5} max={8} step={0.5} value={f.hours_per_day} onChange={e => setF({ ...f, hours_per_day: +e.target.value })} /></div>
          <div><label htmlFor="lv">Current level</label><select id="lv" value={f.level} onChange={e => setF({ ...f, level: e.target.value })}><option>beginner</option><option>intermediate</option><option>advanced</option></select></div>
          <div><label htmlFor="pt">Preferred study time</label><select id="pt" value={f.preferred_study_time} onChange={e => setF({ ...f, preferred_study_time: e.target.value })}><option>morning</option><option>afternoon</option><option>evening</option></select></div>
        </div>
        {err && <ErrorBox>{err}</ErrorBox>}
        <button className="lg" style={{ marginTop: 22 }} disabled={busy}>{busy ? <Spinner /> : <Icon name="arrow" size={16} />}Continue</button>
      </form>
    </div>)
}
