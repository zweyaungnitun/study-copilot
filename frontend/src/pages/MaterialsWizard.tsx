import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type CurriculumPreview, type Material } from '../api'
import { useAuth } from '../auth'
import { ErrorBox, Icon, PageHeader, Spinner, useToast } from '../ui'

const inDays = (n: number) => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10)
const dur = (h: number) => h >= 1 ? `${Math.round(h * 10) / 10} h` : `${Math.max(1, Math.round(h * 60))} min`

export default function MaterialsWizard() {
  const { session } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [materials, setMaterials] = useState<Material[] | null>(null)
  const [picked, setPicked] = useState<string[]>(() => (params.get('ids') || '').split(',').filter(Boolean))
  const [goal, setGoal] = useState('')
  const [deadline, setDeadline] = useState(inDays(30))
  const [hours, setHours] = useState(1.5)
  const [level, setLevel] = useState('intermediate')
  const [skips, setSkips] = useState<string[] | null>(null) // null = server defaults (front/back matter)
  const [preview, setPreview] = useState<CurriculumPreview | null>(null)
  const [busy, setBusy] = useState<'' | 'preview' | 'create'>('')
  const [err, setErr] = useState('')

  useEffect(() => { api.materials().then(m => setMaterials(m.filter(x => x.status === 'ready'))).catch(e => setErr(e.message)) }, [])

  const run = async (skipIds: string[] | null = skips) => {
    if (!picked.length) return
    setBusy('preview'); setErr('')
    try {
      const p = await api.fromMaterials({
        material_ids: picked, goal: goal.trim() || undefined, deadline: new Date(deadline + 'T12:00:00Z').toISOString(),
        hours_per_day: hours, level, skip_section_ids: skipIds,
      })
      setPreview(p)
      setSkips(p.skipped.map(s => s.section_id))
    } catch (e) { setErr((e as Error).message) } finally { setBusy('') }
  }
  const toggleSkip = (id: string) => {
    const next = (skips ?? []).includes(id) ? skips!.filter(x => x !== id) : [...(skips ?? []), id]
    setSkips(next)  // reflect the click now; the preview refreshes when the server answers
    void run(next)
  }
  const create = async () => {
    if (!preview) return
    setBusy('create')
    try {
      await api.applyRoadmap(session!.user_id, preview.proposal)
      await api.buildSchedule()
      toast('ok', `“${preview.proposal.specialization}” created and scheduled`)
      navigate('/schedule')
    } catch (e) { toast('err', (e as Error).message); setBusy('') }
  }

  const chapters = preview?.proposal.subjects.flatMap(s => s.chapters) ?? []
  return (
    <>
      <PageHeader title="Build a track from your materials" back={<Link to="/library" className="back"><Icon name="back" size={16} />Library</Link>}
        sub="Chapters come from your books' own structure; hours from how much there is to read." />
      {err && <ErrorBox>{err}</ErrorBox>}
      <div className="cols">
        <div>
          {!preview ? (
            <div className="card">
              <div className="card-head"><h2>1 · Choose materials</h2></div>
              {!materials ? <Spinner /> : !materials.length
                ? <p className="muted">No processed materials yet. <Link to="/library">Upload one</Link> and wait until it is ready.</p>
                : materials.map(m => (
                  <label key={m.id} className="choice">
                    <input type="checkbox" checked={picked.includes(m.id)} onChange={() => setPicked(p => p.includes(m.id) ? p.filter(x => x !== m.id) : [...p, m.id])} />
                    <span className="grow">{m.filename}</span><span className="muted num">{m.page_count} pages</span></label>))}
            </div>
          ) : (
            <div className="card">
              <div className="card-head">
                <div><h2>{preview.proposal.specialization}</h2>
                  <p className="muted">{chapters.length} chapters · {preview.total_hours} h of {preview.budget_hours} h available ·{' '}
                    {preview.method === 'llm' ? 'grouped by AI' : 'in reading order'}</p></div>
                <button className="ghost sm" onClick={() => setPreview(null)}><Icon name="back" size={14} />Change</button>
              </div>
              {preview.over_budget && (
                <div className="alert err-box"><Icon name="alert" size={16} />
                  <div className="grow">This plan needs {preview.total_hours} h but you have about {preview.budget_hours} h before your deadline.
                    {preview.suggested_skips.length > 0 && <> Skipping {preview.suggested_skips.map(s => s.title).join(', ')} would make it fit.</>}
                    {preview.suggested_skips.length > 0 && <div style={{ marginTop: 8 }}>
                      <button className="sm" disabled={!!busy} onClick={() => run([...(skips ?? []), ...preview.suggested_skips.map(s => s.section_id)])}>Skip these</button></div>}
                  </div></div>)}
              {preview.proposal.subjects.map(s => (
                <div key={s.name} className="plan-subject">
                  <h3>{s.name}</h3>
                  {s.chapters.map(c => (
                    <div key={c.title} className="plan-chapter">
                      <div className="row" style={{ justifyContent: 'space-between' }}><b>{c.title}</b><span className="badge gray num">{dur(c.estimated_hours)}</span></div>
                      <div className="muted plan-sources">{(c.sources ?? []).map(src => `${src.title} (p. ${src.page_start}${src.page_end > src.page_start ? `–${src.page_end}` : ''})`).join(' · ')}</div>
                      {c.prerequisites.length > 0 && <div className="muted plan-sources">After: {c.prerequisites.join(', ')}</div>}
                    </div>))}
                </div>))}
              <div className="row" style={{ marginTop: 16 }}>
                <button className="lg" onClick={create} disabled={!!busy}>{busy === 'create' ? <Spinner /> : <Icon name="calendar" size={16} />}Create track & schedule</button>
                {busy === 'preview' && <Spinner />}
              </div>
            </div>
          )}
        </div>
        <div>
          {!preview ? (
            <form className="card" onSubmit={e => { e.preventDefault(); void run(null) }}>
              <div className="card-head"><h2>2 · Your plan</h2></div>
              <label htmlFor="goal">Goal <span className="hint">· optional</span></label>
              <input id="goal" value={goal} onChange={e => setGoal(e.target.value)} placeholder="e.g. Pass the networking final" maxLength={200} />
              <label htmlFor="dl">Deadline</label>
              <input id="dl" type="date" value={deadline} min={inDays(2)} onChange={e => setDeadline(e.target.value)} required />
              <label htmlFor="hpd">Hours per day</label>
              <input id="hpd" type="number" min={0.5} max={12} step={0.5} value={hours} onChange={e => setHours(Number(e.target.value))} required />
              <label htmlFor="lvl">Your level</label>
              <select id="lvl" value={level} onChange={e => setLevel(e.target.value)}>
                <option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select>
              <button className="lg block" style={{ marginTop: 20 }} disabled={!picked.length || !!busy}>
                {busy === 'preview' ? <Spinner /> : <Icon name="wand" size={16} />}Preview curriculum</button>
            </form>
          ) : (
            <div className="card">
              <div className="card-head"><h2>Sections</h2><span className="muted">untick to skip</span></div>
              <div className="unit-list">{preview.units.map(u => (
                <label key={u.section_id} className={`choice ${(skips ?? []).includes(u.section_id) ? 'skipped' : ''}`}>
                  <input type="checkbox" checked={!(skips ?? []).includes(u.section_id)} disabled={busy === 'create'} onChange={() => toggleSkip(u.section_id)} />
                  <span className="grow"><span>{u.title}</span><span className="muted unit-meta">{u.part ? `${u.part} · ` : ''}p. {u.page_start}–{u.page_end}</span></span>
                  <span className="muted num">{dur(u.hours)}</span></label>))}</div>
              {preview.skipped.some(s => s.reason && s.reason !== 'Skipped by you') &&
                <p className="muted" style={{ fontSize: 13 }}>Front and back matter (preface, index…) is skipped by default.</p>}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
