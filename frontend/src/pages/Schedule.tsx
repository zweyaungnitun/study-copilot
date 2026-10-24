import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, utc, type Schedule, type ScheduledTask, type TaskKind } from '../api'
import { Empty, ErrorBox, Icon, PageHeader, Skeleton, Spinner, useToast, type IconName } from '../ui'

const KIND: Record<TaskKind, [string, IconName, string]> = {
  learn: ['Learn', 'book', ''], review: ['Review', 'cards', 'gray'], practice: ['Practice', 'target', 'green'],
  buffer: ['Buffer', 'clock', 'gray'], mock: ['Mock exam', 'exam', 'yellow'],
}
const iso = (d: Date) => d.toISOString().slice(0, 10)
const monday = (d: Date) => { const x = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())); x.setUTCDate(x.getUTCDate() - ((x.getUTCDay() + 6) % 7)); return x }
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setUTCDate(x.getUTCDate() + n); return x }
const fmtMin = (m: number) => m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}` : `${m}m`

function TaskRow({ t, onSet }: { t: ScheduledTask; onSet: (t: ScheduledTask, s: 'pending' | 'done' | 'skipped') => void }) {
  const [label, icon, tone] = KIND[t.kind] ?? [t.kind, 'list', 'gray']
  const done = t.status === 'done'
  return (
    <li className={`task ${t.status}`}>
      <input type="checkbox" checked={done} aria-label={`Mark ${t.title} done`} disabled={t.status === 'missed'}
        onChange={() => onSet(t, done ? 'pending' : 'done')} />
      <div className="grow">
        <div className="task-title">{t.chapter_id && t.kind === 'learn' ? <Link to={`/chapters/${t.chapter_id}`}>{t.title}</Link> : t.title}</div>
        <div className="row" style={{ gap: 6 }}>
          <span className={`badge ${tone}`}><Icon name={icon} size={12} />{label}</span>
          <span className="muted num">{fmtMin(t.minutes)}</span>
          {t.status === 'missed' && <span className="badge red">Missed</span>}
          {t.status === 'skipped' && <span className="badge gray">Skipped</span>}
        </div>
      </div>
      {t.status === 'pending' && <button className="ghost sm" onClick={() => onSet(t, 'skipped')} title="Skip" aria-label={`Skip ${t.title}`}><Icon name="x" size={14} /></button>}
    </li>
  )
}

export default function SchedulePage() {
  const toast = useToast()
  const [week, setWeek] = useState(() => monday(new Date()))
  const [data, setData] = useState<Schedule | null>(null)
  const [err, setErr] = useState('')
  const [building, setBuilding] = useState(false)

  const load = useCallback(() => api.schedule(iso(week), iso(addDays(week, 6))).then(d => { setData(d); setErr('') })
    .catch(e => setErr(e.message)), [week])
  useEffect(() => { void load() }, [load])

  const build = async () => {
    setBuilding(true)
    try { await api.buildSchedule(); await load(); toast('ok', 'Schedule updated from today') }
    catch (e) { toast('err', (e as Error).message) } finally { setBuilding(false) }
  }
  const setTask = async (t: ScheduledTask, status: 'pending' | 'done' | 'skipped') => {
    const put = (x: ScheduledTask) => setData(d => d && { ...d, tasks: d.tasks.map(y => y.id === x.id ? x : y) })
    put({ ...t, status })  // optimistic; rolled back if the server refuses
    try { put(await api.setTask(t.id, status)) }
    catch (e) { put(t); toast('err', (e as Error).message) }
  }

  const s = data?.summary
  const today = iso(new Date())
  const days = Array.from({ length: 7 }, (_, i) => addDays(week, i))
  const missed = data?.tasks.filter(t => t.status === 'pending' && t.date.slice(0, 10) < today).length ?? 0
  const head = <PageHeader title="Schedule" sub={s ? `Until ${utc(s.deadline).toLocaleDateString(undefined, { month: 'long', day: 'numeric' })} · about ${fmtMin(s.daily_minutes)} a day` : 'A day-by-day plan across your tracks.'}
    actions={<>
      <button className="ghost" onClick={() => setWeek(addDays(week, -7))} aria-label="Previous week"><Icon name="back" size={16} /></button>
      <button className="ghost" onClick={() => setWeek(monday(new Date()))}>This week</button>
      <button className="ghost" onClick={() => setWeek(addDays(week, 7))} aria-label="Next week"><Icon name="arrow" size={16} /></button>
      <button onClick={build} disabled={building}>{building ? <Spinner /> : <Icon name="refresh" size={16} />}{s ? 'Rebuild from today' : 'Build my schedule'}</button></>} />

  if (!data && !err) return <>{head}<Skeleton lines={5} /></>
  return (
    <>
      {head}
      {err && <ErrorBox>{err}</ErrorBox>}
      {s && <div className="card schedule-summary">
        <p style={{ margin: 0 }}>{s.explanation}</p>
        {s.over_capacity && <div className="alert err-box"><Icon name="alert" size={16} />
          About {fmtMin(s.unscheduled_minutes)} of study doesn't fit before your deadline. Try {s.suggested_hours_per_day} h/day, a later deadline, or skip sections.</div>}
        {missed > 0 && <div className="alert err-box"><Icon name="clock" size={16} /><span className="grow">{missed} task{missed > 1 ? 's' : ''} from earlier days {missed > 1 ? 'are' : 'is'} unfinished.</span>
          <button className="sm" onClick={build} disabled={building}>Re-plan the rest</button></div>}
      </div>}
      {!s && !data?.tasks.length ? (
        <Empty icon="calendar" title="No schedule yet" action={<button onClick={build} disabled={building}>{building && <Spinner />}Build my schedule</button>}>
          Turns your tracks into daily sessions with flashcard review, buffer days and mock exams before your deadline.</Empty>
      ) : (
        <div className="week">{days.map(d => {
          const key = iso(d)
          const tasks = data!.tasks.filter(t => t.date.slice(0, 10) === key)
          const total = tasks.reduce((a, t) => a + t.minutes, 0)
          const doneMin = tasks.filter(t => t.status === 'done').reduce((a, t) => a + t.minutes, 0)
          return (
            <section key={key} className={`day card ${key === today ? 'today' : ''} ${tasks.length ? '' : 'day-empty'}`} aria-label={d.toUTCString().slice(0, 11)}>
              <header><b>{d.toLocaleDateString(undefined, { weekday: 'long', timeZone: 'UTC' })}</b>
                <span className="muted">{d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' })}</span>
                {key === today && <span className="badge">Today</span>}
                {total > 0 ? <span className="muted num day-total">{fmtMin(doneMin)} of {fmtMin(total)} done</span> : <span className="muted day-total">Nothing planned</span>}</header>
              {tasks.length > 0 && <ul>{tasks.map(t => <TaskRow key={t.id} t={t} onSet={setTask} />)}</ul>}
            </section>)
        })}</div>
      )}
    </>
  )
}
