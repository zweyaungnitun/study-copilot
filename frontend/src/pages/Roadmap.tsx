import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Chapter, type Roadmap } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import RoadmapAdvisor from './RoadmapAdvisor'
import TrackCard, { chaptersOf, masteryOf, nextUp } from '../TrackCard'
import { CountUp, Empty, Icon, PageHeader, ProgressBar, ProgressRing, Skeleton, Spinner, useToast } from '../ui'

const tone: Record<string, string> = { completed: 'green', in_progress: 'accent', unlocked: 'accent', locked: 'gray' }
const label: Record<string, string> = { completed: 'Completed', in_progress: 'In progress', unlocked: 'Ready', locked: 'Locked' }

const mastery = masteryOf

export default function RoadmapPage() {
  const { session } = useAuth()
  const toast = useToast()
  const uid = session!.user_id
  const [params, setParams] = useSearchParams()
  const { data: tracks, error, loading, setData } = useLoad(() => api.tracks(uid), [uid])
  const [busy, setBusy] = useState(false)
  const [creating, setCreating] = useState(false)

  if (loading) return <><PageHeader title="Roadmap" /><Skeleton lines={4} /><Skeleton lines={3} /></>
  if (!tracks?.length && !creating) return <><PageHeader title="Roadmap" />
    <Empty icon="map" title="No roadmap yet" action={<Link to="/onboarding"><button>Set up your goal</button></Link>}>{error || 'Create a goal to generate your learning path.'}</Empty></>

  const list = tracks ?? []
  const track = list.find(t => t.id === params.get('track')) ?? list[0]
  const select = (id: string) => setParams({ track: id }, { replace: true })
  const replaceTrack = (old: string | null, t: Roadmap) => {
    setData(cur => { const rest = (cur ?? []); return old ? rest.map(x => x.id === old ? t : x) : [...rest, t] })
    select(t.id)
  }

  const regen = async () => {
    if (!track || !confirm(`Regenerate “${track.specialization}”? Progress in this track will be reset. Your other tracks are not affected.`)) return
    setBusy(true)
    try { replaceTrack(track.id, await api.generateRoadmap(uid, undefined, { roadmap_id: track.id })); toast('ok', 'Track regenerated') }
    catch (e) { toast('err', (e as Error).message) } finally { setBusy(false) }
  }
  const archive = async () => {
    if (!track || !confirm(`Stop following “${track.specialization}”? It will be removed from your roadmap.`)) return
    try { await api.archiveTrack(track.id, uid); setData(list.filter(t => t.id !== track.id)); setParams({}, { replace: true }); toast('ok', 'Track removed') }
    catch (e) { toast('err', (e as Error).message) }
  }
  const tabs = (
    <div className="track-tabs" role="tablist" aria-label="Tracks">
      {list.map(t => (
        <button key={t.id} role="tab" aria-selected={t.id === track?.id} className={`track-tab ${t.id === track?.id ? 'on' : ''}`} onClick={() => { setCreating(false); select(t.id) }}>
          <ProgressRing value={mastery(t)} size={22} stroke={3} label={`${Math.round(mastery(t))} percent`} /><span>{t.specialization}</span></button>))}
      <button className={`track-tab add ${creating ? 'on' : ''}`} onClick={() => setCreating(c => !c)}><Icon name="map" size={14} />New track</button>
    </div>)

  const designer = creating && <RoadmapAdvisor mode="design" userId={uid} existing={list} onClose={() => setCreating(false)} onApplied={t => { replaceTrack(null, t); setCreating(false) }} />

  if (!track) return <><PageHeader title="Roadmap" />{tabs}{designer}</>

  const subjects = [...track.subjects].sort((a, b) => a.order_index - b.order_index)
  const chapters = chaptersOf(track)
  const byId = new Map<string, Chapter>(chapters.map(c => [c.id, c]))
  const done = chapters.filter(c => c.status === 'completed').length
  const overall = mastery(track)
  const next = nextUp(track)

  return (
    <>
      <PageHeader title="Roadmap" sub={list.length > 1 ? `${list.length} tracks in parallel — progress is tracked separately for each.` : 'Add more tracks to study several topics in parallel.'} />
      {tabs}
      {designer}
      {list.length > 1 && !creating && <div className="track-grid stagger">{list.map(t => <TrackCard key={t.id} track={t} open={select} />)}</div>}

      <div className="row" style={{ justifyContent: 'space-between', margin: '8px 0 16px' }}>
        <div><h2 style={{ margin: 0 }}>{track.specialization}</h2>
          <p className="muted" style={{ margin: 0 }}>{Math.round(track.total_estimated_hours)} hours · {subjects.length} subjects · {chapters.length} chapters</p></div>
        <div className="row">
          <button className="ghost" disabled={busy} onClick={regen}>{busy ? <Spinner /> : <Icon name="refresh" size={16} />}{busy ? 'Regenerating…' : 'Regenerate'}</button>
          <button className="ghost" onClick={archive}>Remove</button></div></div>
      <div className="card progress-card">
        <ProgressRing value={overall} size={104} stroke={10} tone={done === chapters.length ? 'green' : 'accent'} label={`${Math.round(overall)} percent mastery`}>
          <b className="num" style={{ fontSize: 22 }}><CountUp value={Math.round(overall)} />%</b></ProgressRing>
        <div className="progress-stats">
          <div><b className="num"><CountUp value={done} />/{chapters.length}</b><span className="muted">chapters done</span></div>
          <div><b className="num"><CountUp value={Math.round(chapters.filter(c => c.status !== 'completed').reduce((a, c) => a + c.estimated_hours, 0))} />h</b><span className="muted">left to study</span></div>
          <div><b className="num"><CountUp value={chapters.filter(c => c.status === 'in_progress').length} /></b><span className="muted">in progress</span></div>
        </div>
        {next ? <div className="progress-next"><span className="muted">{next.status === 'in_progress' ? 'Continue where you left off' : 'Up next'}</span><b>{next.title}</b>
            <Link to={`/chapters/${next.id}`}><button>{next.status === 'in_progress' ? 'Continue' : 'Start'} <Icon name="arrow" size={16} /></button></Link></div>
          : done === chapters.length && <p className="muted">🎉 Every chapter is complete. Review flashcards to keep it fresh.</p>}
      </div>
      <RoadmapAdvisor key={track.id} mode="discuss" userId={uid} track={track} onApplied={t => replaceTrack(track.id, t)} />
      {subjects.map((s, i) => {
        const sd = s.chapters.filter(c => c.status === 'completed').length
        return (
        <div className="card" key={s.id}>
          <div className="card-head"><h2><span className="muted num">{String(i + 1).padStart(2, '0')}</span>&nbsp;&nbsp;{s.name}</h2><span className="muted">{sd}/{s.chapters.length} done</span></div>
          <div className="path">{s.chapters.map(c => {
            const locked = c.status === 'locked'
            const pct = Math.round(c.mastery_score)
            const blockers = c.prerequisites.map(id => byId.get(id)).filter(p => p && p.status !== 'completed').map(p => p!.title)
            const node = locked ? <Icon name="lock" size={16} /> : c.status === 'completed' ? <Icon name="check" size={18} /> : <Icon name="book" size={16} />
            const body = <>
              <div className="path-text"><div className="title">{c.title}</div>
                <div className="muted">{locked && blockers.length ? `Finish first: ${blockers.join(', ')}` : `${c.estimated_hours}h`}</div></div>
              <div className="row" style={{ flexWrap: 'nowrap' }}>
                <span className={`badge ${tone[c.status] ?? 'gray'}`}>{label[c.status] ?? c.status}</span>
                <div className="meter"><ProgressBar value={pct} tone="green" /><span>{pct}%</span></div>
              </div></>
            return (
              <div key={c.id} className={`path-step ${c.status}`}>
                <span className="path-node" aria-hidden="true">{node}</span>
                {locked ? <div className="path-card locked" title="Complete the prerequisite chapters to unlock">{body}</div>
                  : <Link to={`/chapters/${c.id}`} className="path-card">{body}</Link>}
              </div>)
          })}</div>
        </div>)})}
    </>
  )
}
