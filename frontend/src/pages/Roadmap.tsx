import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Empty, Icon, PageHeader, ProgressBar, Skeleton, Spinner, useToast } from '../ui'

const tone: Record<string, string> = { completed: 'green', mastered: 'green', in_progress: 'accent', available: 'accent', locked: 'gray' }
const pretty = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())

export default function RoadmapPage() {
  const { session } = useAuth()
  const toast = useToast()
  const uid = session!.user_id
  const { data, error, loading, setData } = useLoad(() => api.roadmap(uid), [uid])
  const [busy, setBusy] = useState(false)
  const regen = async () => {
    if (!confirm('Regenerate your roadmap? Your current plan will be replaced.')) return
    setBusy(true)
    try { setData(await api.generateRoadmap(uid)); toast('ok', 'Roadmap regenerated') }
    catch (e) { toast('err', (e as Error).message) } finally { setBusy(false) }
  }

  if (loading) return <><PageHeader title="Roadmap" /><Skeleton lines={4} /><Skeleton lines={3} /></>
  if (!data) return <><PageHeader title="Roadmap" />
    <Empty icon="map" title="No roadmap yet" action={<Link to="/onboarding"><button>Set up your goal</button></Link>}>{error || 'Create a goal to generate your learning path.'}</Empty></>

  const chapters = data.subjects.flatMap(s => s.chapters)
  const overall = chapters.length ? (chapters.reduce((a, c) => a + c.mastery_score, 0) / chapters.length) * 100 : 0
  return (
    <>
      <PageHeader title={data.specialization} sub={`${Math.round(data.total_estimated_hours)} hours · ${data.subjects.length} subjects · ${chapters.length} chapters`}
        actions={<button className="ghost" disabled={busy} onClick={regen}>{busy ? <Spinner /> : <Icon name="refresh" size={16} />}Regenerate</button>} />
      <div className="card"><div className="card-head"><h2>Overall mastery</h2><b className="num">{Math.round(overall)}%</b></div><ProgressBar value={overall} tone="green" /></div>
      {[...data.subjects].sort((a, b) => a.order_index - b.order_index).map((s, i) => (
        <div className="card" key={s.id}>
          <div className="card-head"><h2><span className="muted num">{String(i + 1).padStart(2, '0')}</span>&nbsp;&nbsp;{s.name}</h2><span className="muted">{s.chapters.length} chapters</span></div>
          <div className="list">{s.chapters.map(c => {
            const locked = c.status === 'locked'
            const pct = Math.round(c.mastery_score * 100)
            const inner = <>
              <div className="main"><span className="file-ic">{locked ? <Icon name="lock" size={16} /> : <Icon name="book" size={16} />}</span>
                <div><div className="title">{c.title}</div><div className="muted">{c.estimated_hours}h</div></div></div>
              <div className="row" style={{ flexWrap: 'nowrap' }}>
                <span className={`badge ${tone[c.status] ?? 'gray'}`}>{pretty(c.status)}</span>
                <div className="meter"><ProgressBar value={pct} tone="green" /><span>{pct}%</span></div>
              </div></>
            return locked ? <div key={c.id} className="item locked">{inner}</div> : <Link key={c.id} to={`/chapters/${c.id}`} className="item">{inner}</Link>
          })}</div>
        </div>))}
    </>
  )
}
