import { Link } from 'react-router-dom'
import type { Roadmap } from './api'
import { Icon, ProgressRing } from './ui'

export const chaptersOf = (t: Roadmap) => t.subjects.flatMap(s => s.chapters)
export const masteryOf = (t: Roadmap) => { const c = chaptersOf(t); return c.length ? c.reduce((a, x) => a + x.mastery_score, 0) / c.length : 0 }
export const nextUp = (t: Roadmap) => { const c = chaptersOf(t); return c.find(x => x.status === 'in_progress') ?? c.find(x => x.status === 'unlocked') }

/** Summary card for one track: progress ring, what's next and quick actions. */
export default function TrackCard({ track, open }: { track: Roadmap; open?: (id: string) => void }) {
  const cs = chaptersOf(track), done = cs.filter(c => c.status === 'completed').length
  const pct = masteryOf(track), next = nextUp(track)
  const hoursLeft = Math.round(cs.filter(c => c.status !== 'completed').reduce((a, c) => a + c.estimated_hours, 0))
  const complete = cs.length > 0 && done === cs.length
  return (
    <article className="track-card">
      <div className="track-card-head">
        <ProgressRing value={pct} size={64} stroke={7} tone={complete ? 'green' : 'accent'} label={`${Math.round(pct)} percent mastery`}>
          <b className="num" style={{ fontSize: 14 }}>{Math.round(pct)}%</b></ProgressRing>
        <div className="track-card-title">
          <h3>{track.specialization}</h3>
          <p className="muted">{done}/{cs.length} chapters · {hoursLeft}h left</p>
        </div>
      </div>
      <div className="track-card-next">
        <span className="muted">{complete ? 'Track complete' : next?.status === 'in_progress' ? 'Continue' : 'Up next'}</span>
        <b>{complete ? 'All chapters done 🎉' : next?.title ?? 'Finish prerequisites to unlock the next chapter'}</b>
      </div>
      <div className="row track-card-actions">
        {next && <Link to={`/chapters/${next.id}`}><button>{next.status === 'in_progress' ? 'Continue' : 'Start'} <Icon name="arrow" size={15} /></button></Link>}
        {next && <Link to={`/tutor?chapter=${next.id}`}><button className="ghost" aria-label={`Ask the tutor about ${next.title}`}><Icon name="chat" size={15} /></button></Link>}
        {open ? <button className="ghost" onClick={() => open(track.id)}>View roadmap</button> : <Link to={`/roadmap?track=${track.id}`}><button className="ghost">View roadmap</button></Link>}
      </div>
    </article>
  )
}
