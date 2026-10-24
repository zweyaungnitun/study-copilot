import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type ResourceLink, type StudyGuide } from '../api'
import { useLoad } from '../hooks'
import { Empty, ErrorBox, Icon, type IconName, Markdown, PageHeader, ProgressBar, Segmented, Skeleton, Spinner, useToast } from '../ui'

const resourceIcon: Record<string, IconName> = { video: 'spark', article: 'file', docs: 'book', course: 'map', practice: 'target', search: 'search', link: 'arrow' }

function LearningPath({ guide }: { guide: StudyGuide }) {
  return (
    <div className="card">
      <div className="card-head"><h2>Learning path</h2><span className="muted">{guide.lesson_steps.reduce((m, s) => m + s.minutes, 0)} min</span></div>
      {guide.overview && <p style={{ marginBottom: 16 }}>{guide.overview}</p>}
      <h3 className="muted" style={{ fontSize: 13, marginBottom: 6 }}>You will be able to</h3>
      <ul style={{ margin: '0 0 16px', paddingLeft: 20 }}>{guide.objectives.map((o, i) => <li key={i}>{o}</li>)}</ul>
      <h3 className="muted" style={{ fontSize: 13, marginBottom: 6 }}>Steps</h3>
      <ol className="list" style={{ margin: '0 0 16px', padding: 0, listStyle: 'none' }}>
        {guide.lesson_steps.map((s, i) => <li key={i} className="item step">
          <div className="row" style={{ justifyContent: 'space-between', width: '100%' }}><b>{i + 1}. {s.title}</b><span className="badge gray">{s.minutes} min</span></div>
          {s.activity && <span className="muted">{s.activity}</span>}</li>)}
      </ol>
      <h3 className="muted" style={{ fontSize: 13, marginBottom: 6 }}>Practice</h3>
      <ul style={{ margin: 0, paddingLeft: 20 }}>{guide.practice.map((p, i) => <li key={i}>{p}</li>)}</ul>
    </div>
  )
}

function Resources({ chapterId, links, onChange }: { chapterId: string; links: ResourceLink[]; onChange: (l: ResourceLink[]) => void }) {
  const toast = useToast()
  const [label, setLabel] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try { const r = await api.addResource(chapterId, { label: label.trim() || url.trim(), url: url.trim() }); onChange([...links, r]); setLabel(''); setUrl('') }
    catch (err) { toast('err', (err as Error).message) } finally { setBusy(false) }
  }
  const remove = async (id: string) => {
    try { await api.deleteResource(chapterId, id); onChange(links.filter(l => l.id !== id)) }
    catch (err) { toast('err', (err as Error).message) }
  }
  return (
    <div className="card">
      <div className="card-head"><h2>Resources</h2></div>
      <div className="list">
        {links.map(l => <div key={l.id} className="item">
          <a href={l.url} target="_blank" rel="noopener noreferrer" className="row" style={{ gap: 10, minWidth: 0 }}>
            <Icon name={resourceIcon[l.type] || 'arrow'} size={16} /><span>{l.label}</span>
            {l.source === 'user' && <span className="badge">Yours</span>}
            {l.source === 'search' && <span className="badge gray">Search</span>}</a>
          <button className="ghost sm" aria-label={`Remove ${l.label}`} onClick={() => remove(l.id)}><Icon name="x" size={14} /></button>
        </div>)}
        {!links.length && <p className="muted">No links yet.</p>}
      </div>
      <form className="row" onSubmit={add} style={{ marginTop: 14 }}>
        <input placeholder="Title (optional)" value={label} onChange={e => setLabel(e.target.value)} maxLength={200} style={{ flex: '1 1 160px' }} />
        <input placeholder="https://…" type="url" required value={url} onChange={e => setUrl(e.target.value)} style={{ flex: '2 1 220px' }} />
        <button className="ghost" disabled={busy || !url.trim()}>{busy ? <Spinner /> : <Icon name="plus" size={16} />}Add link</button>
      </form>
    </div>
  )
}

const tiers: ['simple_content' | 'detailed_content' | 'exam_content' | 'cheat_sheet', string][] =
  [['simple_content', 'Simple'], ['detailed_content', 'Detailed'], ['exam_content', 'Exam'], ['cheat_sheet', 'Cheat sheet']]

export default function ChapterPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const toast = useToast()
  const info = useLoad(() => api.chapter(id!), [id])
  const locked = info.data?.status === 'locked'
  // Notes are generated on demand (can take several seconds), so only request them for reachable chapters.
  const notes = useLoad(async () => (info.data && !locked ? api.notes(id!) : null), [id, info.data?.status === 'locked', !!info.data])
  const guide = useLoad(async () => (info.data && !locked ? api.guide(id!) : null), [id, info.data?.status === 'locked', !!info.data])
  const [tier, setTier] = useState<(typeof tiers)[number][0]>('simple_content')
  const [busy, setBusy] = useState<'cards' | 'done' | 'reopen' | ''>('')

  const back = <Link to={info.data ? `/roadmap?track=${info.data.roadmap_id}` : '/roadmap'} className="back"><Icon name="back" size={15} />{info.data?.roadmap_name || 'Roadmap'}</Link>
  const gen = async () => {
    setBusy('cards')
    try { const c = await api.genCards(id!); toast('ok', `Created ${c.length} flashcards`); nav('/flashcards') }
    catch (e) { toast('err', (e as Error).message) } finally { setBusy('') }
  }
  const complete = async () => {
    setBusy('done')
    try {
      const r = await api.completeChapter(id!)
      info.setData(r.chapter)
      toast('ok', r.unlocked.length ? `Chapter complete — unlocked: ${r.unlocked.map(u => u.title).join(', ')}` : 'Chapter complete')
    } catch (e) { toast('err', (e as Error).message) } finally { setBusy('') }
  }

  const reopen = async () => {
    setBusy('reopen')
    try {
      const r = await api.reopenChapter(id!)
      info.setData(r.chapter)
      toast('ok', r.unlocked.length ? `Reopened — re-locked: ${r.unlocked.map(u => u.title).join(', ')}` : 'Chapter reopened')
    } catch (e) { toast('err', (e as Error).message) } finally { setBusy('') }
  }

  if (info.loading) return <><PageHeader title="Chapter" back={back} /><Skeleton lines={3} /></>
  if (info.error || !info.data) return <><PageHeader title="Chapter" back={back} /><ErrorBox>{info.error}</ErrorBox></>
  const c = info.data
  const finished = c.status === 'completed'

  if (locked) return <>
    <PageHeader title={c.title} back={back} sub={c.subject_name} />
    <Empty icon="lock" title="This chapter is locked" action={<Link to="/roadmap"><button>Back to roadmap</button></Link>}>
      Complete {c.prerequisites.filter(p => p.status !== 'completed').map(p => p.title).join(', ') || 'the earlier chapters'} first.</Empty></>

  return (
    <>
      <PageHeader title={c.title} back={back}
        sub={<>{c.subject_name} · {c.estimated_hours}h · <span className={`badge ${finished ? 'green' : 'accent'}`}>{finished ? 'Completed' : 'In progress'}</span></>}
        actions={<>
          <Link to={`/tutor?chapter=${id}`}><button className="ghost"><Icon name="chat" size={16} />Ask the tutor</button></Link>
          <button className="ghost" onClick={gen} disabled={!!busy}>{busy === 'cards' ? <Spinner /> : <Icon name="cards" size={16} />}Make flashcards</button>
          {finished ? <button className="ghost" onClick={reopen} disabled={!!busy}>{busy === 'reopen' ? <Spinner /> : <Icon name="refresh" size={16} />}Reopen</button> : <button onClick={complete} disabled={!!busy}>{busy === 'done' ? <Spinner /> : <Icon name="check" size={16} />}Mark complete</button>}</>} />
      {!!c.sources?.length && <div className="card chapter-sources">
        <div className="card-head"><h2><Icon name="book" size={16} /> Read in your materials</h2></div>
        <ul>{c.sources.map(src => <li key={src.section_id}><b>{src.title}</b> <span className="muted">· {src.filename}, p. {src.page_start}{src.page_end > src.page_start && `–${src.page_end}`}</span></li>)}</ul>
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>Notes, flashcards, exams and the tutor use these pages first.</p>
      </div>}
      {guide.loading ? <div className="card"><Skeleton lines={4} /></div>
        : guide.data ? <LearningPath guide={guide.data} />
        : guide.error ? <ErrorBox>{guide.error}</ErrorBox> : null}
      <div style={{ marginBottom: 16 }}><Segmented label="Detail level" value={tier} onChange={setTier} options={tiers} /></div>
      {notes.loading ? <><p className="muted" style={{ marginBottom: 12 }}>Writing your notes for “{c.title}” — this takes a few seconds the first time.</p><Skeleton lines={5} /></>
        : notes.error || !notes.data ? <ErrorBox>{notes.error || 'Could not load notes.'}</ErrorBox>
        : <div className="card" style={{ padding: 28 }}>{notes.data[tier] ? <Markdown text={notes.data[tier]!} /> : <p className="muted">Nothing here yet.</p>}</div>}
      {guide.data && <Resources chapterId={id!} links={guide.data.resources} onChange={resources => guide.setData({ ...guide.data!, resources })} />}
      <div className="card"><div className="card-head"><h2>Mastery</h2><b className="num">{Math.round(c.mastery_score)}%</b></div>
        <ProgressBar value={c.mastery_score} tone="green" />
        <p className="muted" style={{ marginTop: 8 }}>Review this chapter's flashcards to raise mastery. Reaching 80% completes it automatically.</p></div>
      {finished && c.next_chapter && <div className="card row" style={{ justifyContent: 'space-between' }}>
        <div><div className="muted">Up next</div><b>{c.next_chapter.title}</b></div>
        <Link to={`/chapters/${c.next_chapter.id}`}><button>Continue <Icon name="arrow" size={16} /></button></Link></div>}
    </>
  )
}
