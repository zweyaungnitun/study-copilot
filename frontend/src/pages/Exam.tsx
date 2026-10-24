import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, utc, type Attempt, type Exam, type ExamResult, type ProctorEventType } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { ErrorBox, Icon, PageHeader, ProgressRing, Segmented, Spinner, useToast, type IconName } from '../ui'

const HEARTBEAT_MS = 10_000
const RULES: [IconName, string][] = [
  ['eye', 'Stay on this tab. Switching tabs or windows is recorded.'],
  ['sidebar', 'The exam runs in fullscreen. Leaving fullscreen is recorded.'],
  ['copy', 'Copy, paste and right-click are disabled and recorded.'],
  ['shield', 'A proctor may message you or end the exam if your integrity score drops.'],
]

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.max(0, s % 60)).padStart(2, '0')}`

/**
 * Browser-side proctoring for one running attempt: queues integrity events, flushes them with a
 * heartbeat, and surfaces proctor warnings or a termination.
 */
function useProctor(examId: string | null, onTerminated: (reason: string) => void) {
  const queue = useRef<{ type: ProctorEventType; detail?: string }[]>([])
  const [integrity, setIntegrity] = useState(100)
  const [warning, setWarning] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(!!document.fullscreenElement)
  const flushing = useRef(false)

  const flush = useCallback(async () => {
    if (!examId || flushing.current) return
    flushing.current = true
    const events = queue.current.splice(0, 50)
    try {
      const beat = await api.proctor(examId, events)
      setIntegrity(beat.integrity_score)
      if (beat.warning) setWarning(beat.warning)
      if (beat.status === 'terminated') onTerminated(beat.termination_reason || 'Ended by a proctor')
    } catch { queue.current.unshift(...events) /* retry with the next heartbeat */ }
    finally { flushing.current = false }
  }, [examId, onTerminated])

  const record = useCallback((type: ProctorEventType, detail?: string) => {
    queue.current.push({ type, detail })
    void flush()
  }, [flush])

  useEffect(() => {
    if (!examId) return
    setFullscreen(!!document.fullscreenElement)
    const vis = () => { if (document.visibilityState === 'hidden') record('tab_hidden') }
    // A tab switch also blurs the window; only count blur when the page is still visible (another app/window).
    const blur = () => { if (document.visibilityState === 'visible') record('window_blur') }
    const fs = () => {
      const on = !!document.fullscreenElement
      setFullscreen(on)
      record(on ? 'fullscreen_enter' : 'fullscreen_exit')
    }
    const clip = (type: 'copy' | 'paste') => (e: ClipboardEvent) => { e.preventDefault(); record(type) }
    const onCopy = clip('copy'), onPaste = clip('paste')
    const menu = (e: MouseEvent) => { e.preventDefault(); record('context_menu') }
    const key = (e: KeyboardEvent) => { if (e.key === 'PrintScreen') record('print_screen') }
    document.addEventListener('visibilitychange', vis)
    window.addEventListener('blur', blur)
    document.addEventListener('fullscreenchange', fs)
    document.addEventListener('copy', onCopy)
    document.addEventListener('cut', onCopy)
    document.addEventListener('paste', onPaste)
    document.addEventListener('contextmenu', menu)
    window.addEventListener('keyup', key)
    const screenDetails = (window.screen as Screen & { isExtended?: boolean })
    if (screenDetails.isExtended) record('multiple_screens', 'Extended display detected at start')
    record('exam_started')
    const beat = window.setInterval(() => void flush(), HEARTBEAT_MS)
    return () => {
      document.removeEventListener('visibilitychange', vis)
      window.removeEventListener('blur', blur)
      document.removeEventListener('fullscreenchange', fs)
      document.removeEventListener('copy', onCopy)
      document.removeEventListener('cut', onCopy)
      document.removeEventListener('paste', onPaste)
      document.removeEventListener('contextmenu', menu)
      window.removeEventListener('keyup', key)
      window.clearInterval(beat)
    }
  }, [examId, record, flush])

  return { integrity, warning, dismissWarning: () => setWarning(null), fullscreen, flush }
}

const enterFullscreen = () => document.documentElement.requestFullscreen?.().catch(() => { /* not allowed: recorded as exit */ })
const exitFullscreen = () => { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}) }

export default function ExamPage() {
  const { session } = useAuth()
  const toast = useToast()
  const [count, setCount] = useState(10)
  const [minutes, setMinutes] = useState(30)
  const [agreed, setAgreed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [exam, setExam] = useState<Exam | null>(null)
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [idx, setIdx] = useState(0)
  const [left, setLeft] = useState<number | null>(null)  // null until the countdown has ticked
  const [result, setResult] = useState<ExamResult | null>(null)
  const [ended, setEnded] = useState<string | null>(null)
  const history = useLoad(() => api.myAttempts(), [result, ended])

  const onTerminated = useCallback((reason: string) => { setEnded(reason); setExam(null); exitFullscreen() }, [])
  const proctor = useProctor(exam?.exam_id ?? null, onTerminated)

  const submit = useCallback(async (auto = false) => {
    if (!exam) return
    setBusy(true)
    try {
      await proctor.flush()
      const r = await api.submitExam(exam.exam_id, session!.user_id,
        Object.entries(answers).map(([question_id, selected_option_index]) => ({ question_id, selected_option_index })))
      setResult(r); setExam(null); exitFullscreen()
      if (auto) toast('ok', 'Time is up. Your exam was submitted.')
    } catch (e) {
      const msg = (e as Error).message
      if (msg.includes('ended by a proctor')) onTerminated(msg)
      else toast('err', msg)
    } finally { setBusy(false) }
  }, [exam, answers, session, proctor, toast, onTerminated])

  // Countdown from the server's start time; submits automatically at zero.
  useEffect(() => {
    if (!exam) return
    const end = utc(exam.started_at).getTime() + exam.time_limit_minutes * 60_000
    const tick = () => setLeft(Math.max(0, Math.round((end - Date.now()) / 1000)))
    tick()
    const t = window.setInterval(tick, 1000)
    return () => window.clearInterval(t)
  }, [exam])
  const submitRef = useRef(submit)
  useEffect(() => { submitRef.current = submit }, [submit])
  useEffect(() => { if (exam && left === 0) void submitRef.current(true) }, [exam, left])

  async function start() {
    setErr(''); setBusy(true)
    try {
      await enterFullscreen()
      const e = await api.generateExam(session!.user_id, count, minutes)
      setLeft(null); setExam(e); setAnswers({}); setIdx(0); setResult(null); setEnded(null)
    } catch (e) { setErr((e as Error).message); exitFullscreen() }
    finally { setBusy(false) }
  }

  /* ---------- running ---------- */
  if (exam) {
    const q = exam.questions[idx]
    const answered = Object.keys(answers).length
    return (
      <div className="exam-run" onCopy={e => e.preventDefault()}>
        <div className="exam-bar card">
          <div><b>{exam.title}</b><div className="muted">{answered}/{exam.questions.length} answered</div></div>
          <div className="row">
            <span className={`badge ${proctor.integrity >= 80 ? 'green' : proctor.integrity >= 50 ? 'yellow' : 'red'}`} title="Integrity score">
              <Icon name="shield" size={12} />Integrity {proctor.integrity}</span>
            <span className={`exam-timer num ${left !== null && left < 60 ? 'low' : ''}`} aria-live="off"><Icon name="clock" size={16} />{left === null ? '—' : mmss(left)}</span>
          </div>
        </div>

        {!proctor.fullscreen && <div className="alert err-box" role="alert"><Icon name="alert" size={16} />
          <span className="grow">You left fullscreen. This has been recorded.</span>
          <button className="sm" onClick={enterFullscreen}>Return to fullscreen</button></div>}

        {/* Portal: <main>'s entry animation would otherwise trap position:fixed */}
        {proctor.warning && createPortal(<div className="modal-backdrop"><div className="modal card" role="alertdialog" aria-labelledby="warn-h">
          <span className="stat-icon orange"><Icon name="alert" /></span>
          <h2 id="warn-h">Message from your proctor</h2><p>{proctor.warning}</p>
          <button onClick={proctor.dismissWarning}>I understand</button></div></div>, document.body)}

        <div className="card exam-q">
          <div className="muted">Question {idx + 1} of {exam.questions.length} · {q.chapter_title}</div>
          <h2>{q.question}</h2>
          <div role="radiogroup" aria-label="Options">{q.options.map((o, i) => (
            <label key={i} className="choice">
              <input type="radio" name={q.id} checked={answers[q.id] === i} onChange={() => setAnswers({ ...answers, [q.id]: i })} />
              <span className="grow">{o}</span></label>))}</div>
          <div className="row" style={{ justifyContent: 'space-between', marginTop: 18 }}>
            <button className="ghost" disabled={idx === 0} onClick={() => setIdx(idx - 1)}><Icon name="back" size={16} />Previous</button>
            {idx < exam.questions.length - 1
              ? <button onClick={() => setIdx(idx + 1)}>Next<Icon name="arrow" size={16} /></button>
              : <button onClick={() => submit()} disabled={busy}>{busy && <Spinner />}Submit exam</button>}
          </div>
        </div>
        <div className="exam-nav" aria-label="Jump to question">{exam.questions.map((x, i) => (
          <button key={x.id} className={`${i === idx ? 'on' : ''} ${answers[x.id] !== undefined ? 'done' : ''}`} onClick={() => setIdx(i)}
            aria-label={`Question ${i + 1}${answers[x.id] !== undefined ? ', answered' : ''}`}>{i + 1}</button>))}</div>
      </div>
    )
  }

  /* ---------- setup / result ---------- */
  return (
    <>
      <PageHeader title="Mock exam" sub="A timed, proctored practice exam across your active tracks." />
      {ended && <div className="alert err-box" role="alert"><Icon name="shield" size={16} /><span><b>Your exam was ended by a proctor.</b> {ended}</span></div>}
      {result && (
        <div className="card exam-result">
          <ProgressRing value={result.percentage} size={110} stroke={10} tone={result.passed ? 'green' : 'spark'}>
            <b className="num">{Math.round(result.percentage)}%</b></ProgressRing>
          <div className="grow">
            <div className="row"><h2 style={{ margin: 0 }}>{result.score}/{result.max_score}</h2>
              <span className={`badge ${result.passed ? 'green' : 'red'}`}><Icon name={result.passed ? 'check' : 'x'} size={12} />{result.passed ? 'Passed' : 'Not yet'}</span>
              {result.integrity_score !== undefined && <span className={`badge ${result.integrity_score >= 80 ? 'green' : result.integrity_score >= 50 ? 'yellow' : 'red'}`}>
                <Icon name="shield" size={12} />Integrity {result.integrity_score}</span>}</div>
            <p>{result.overall_feedback}</p>
            {result.points_lost_by_category.map(c => <p key={c.chapter_title} className="muted">−{c.points_lost} · <b>{c.chapter_title}</b>: {c.recommendation}</p>)}
          </div>
        </div>)}

      <div className="cols">
        <div className="card">
          <div className="card-head"><h2>{result || ended ? 'Take another exam' : 'Set up your exam'}</h2></div>
          <label>Questions</label>
          <Segmented label="Questions" value={count} onChange={setCount} options={[[5, '5'], [10, '10'], [20, '20']]} />
          <label style={{ marginTop: 16 }}>Time limit</label>
          <Segmented label="Time limit" value={minutes} onChange={setMinutes} options={[[15, '15 min'], [30, '30 min'], [60, '60 min']]} />
          <ul className="exam-rules">{RULES.map(([ic, t]) => <li key={t}><Icon name={ic} size={16} />{t}</li>)}</ul>
          <label className="choice"><input type="checkbox" checked={agreed} onChange={e => setAgreed(e.target.checked)} />
            <span className="grow">I understand this exam is proctored.</span></label>
          {err && <ErrorBox>{err}</ErrorBox>}
          <button className="lg" style={{ marginTop: 16 }} disabled={!agreed || busy} onClick={start}>{busy ? <Spinner /> : <Icon name="exam" size={16} />}Start exam</button>
        </div>
        <div className="card">
          <div className="card-head"><h2>History</h2></div>
          {history.loading ? <Spinner /> : !history.data?.length ? <p className="muted">No exams yet.</p> : (
            <div className="list">{history.data.slice(0, 8).map((a: Attempt) => (
              <div className="item" key={a.id}>
                <div className="main"><div><div className="title">{utc(a.started_at).toLocaleDateString()}</div>
                  <div className="muted">{a.question_count} questions · integrity {a.integrity_score}</div></div></div>
                {a.status === 'terminated' ? <span className="badge red">Ended</span>
                  : a.status === 'submitted' ? <b className="num">{Math.round(a.percentage ?? 0)}%</b>
                    : <span className="badge gray">Unfinished</span>}
              </div>))}</div>)}
        </div>
      </div>
    </>
  )
}
