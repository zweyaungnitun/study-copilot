import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, PROCESSING, SOURCE_LABEL, type Material, type RAGResult, type Section, type SourceType, type Storage } from '../api'
import { Empty, ErrorBox, Icon, Markdown, PageHeader, ProgressBar, Spinner, useToast } from '../ui'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.markdown,.ipynb'
const STAGE: Record<string, string> = {
  pending: 'Queued', extracting: 'Reading pages', outlining: 'Finding chapters', embedding: 'Indexing', ready: 'Ready', failed: 'Failed',
}
const tone = (s: string) => s === 'ready' ? 'green' : s === 'failed' ? 'red' : 'yellow'
const POLL_MS = 2000

function Outline({ id }: { id: string }) {
  const [sections, setSections] = useState<Section[] | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.outline(id).then(o => setSections(o.sections)).catch(e => setErr(e.message)) }, [id])
  if (err) return <ErrorBox>{err}</ErrorBox>
  if (!sections) return <div className="outline"><Spinner /></div>
  if (!sections.length) return <p className="muted outline">No outline yet.</p>
  return (
    <ol className="outline">{sections.map(s => (
      <li key={s.id} style={{ paddingLeft: (s.level - 1) * 18 }} title={s.summary || undefined}>
        <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
          <span className={s.level === 1 ? 'title' : ''}>{s.title}</span>
          <span className="muted num" style={{ whiteSpace: 'nowrap' }}>p. {s.page_start}{s.page_end > s.page_start && `–${s.page_end}`}</span></div>
        {s.summary && s.summary !== s.title && s.level <= 2 && <div className="muted outline-summary">{s.summary}</div>}
      </li>))}</ol>
  )
}

export default function Library() {
  const toast = useToast()
  const navigate = useNavigate()
  const [items, setItems] = useState<Material[] | null>(null)
  const [storage, setStorage] = useState<Storage | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(0)
  const [over, setOver] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [q, setQ] = useState('')
  const [searching, setSearching] = useState(false)
  const [res, setRes] = useState<RAGResult | null>(null)

  const refresh = useCallback(async () => {
    try { const [m, s] = await Promise.all([api.materials(), api.storage()]); setItems(m); setStorage(s); setErr('') }
    catch (e) { setErr((e as Error).message) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  // Poll while anything is still being processed.
  const processing = !!items?.some(m => PROCESSING.includes(m.status))
  useEffect(() => {
    if (!processing) return
    const t = window.setInterval(() => void refresh(), POLL_MS)
    return () => window.clearInterval(t)
  }, [processing, refresh])

  const [link, setLink] = useState('')
  const [crawl, setCrawl] = useState(true)
  const [adding, setAdding] = useState(false)
  const addLink = async (e: FormEvent) => {
    e.preventDefault(); setAdding(true)
    try {
      const m = await api.addWebSource({ url: link, include_linked_pages: crawl })
      toast('ok', m.duplicate ? 'That link is already in your library' : 'Link added — reading the pages')
      setLink(''); await refresh()
    } catch (x) { toast('err', (x as Error).message) } finally { setAdding(false) }
  }

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy(files.length)
    for (const f of Array.from(files)) {
      try {
        const m = await api.upload(f)
        toast('ok', m.duplicate ? `${f.name} is already in your library` : `${f.name} uploaded — processing`)
      } catch (e) { toast('err', `${f.name}: ${(e as Error).message}`) }
      setBusy(b => b - 1)
    }
    await refresh()
  }
  const remove = async (m: Material) => {
    if (!confirm(`Delete ${m.filename}? Its outline, search index and links from your chapters are removed too.`)) return
    try { await api.deleteMaterial(m.id); setPicked(p => p.filter(x => x !== m.id)); toast('ok', `${m.filename} deleted`); await refresh() }
    catch (e) { toast('err', (e as Error).message) }
  }
  const setType = async (m: Material, t: SourceType) => {
    try {
      const u = await api.setMaterialType(m.id, t)
      toast('ok', PROCESSING.includes(u.status) ? `${m.filename} is now a ${SOURCE_LABEL[t].toLowerCase()} — re-indexing` : `${m.filename} is now a ${SOURCE_LABEL[t].toLowerCase()}`)
      await refresh()
    } catch (e) { toast('err', (e as Error).message) }
  }
  const reindex = async (m: Material) => {
    try { await api.reindexMaterial(m.id); toast('ok', `Re-indexing ${m.filename}`); await refresh() }
    catch (e) { toast('err', (e as Error).message) }
  }
  const ask = async (e: FormEvent) => {
    e.preventDefault(); setSearching(true)
    try { setRes(await api.queryMaterials(q)) } catch (x) { toast('err', (x as Error).message) } finally { setSearching(false) }
  }
  const toggle = (id: string) => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id])
  const ready = items?.filter(m => m.status === 'ready') ?? []

  return (
    <>
      <PageHeader title="Library" sub="Your textbooks, notes, past papers and web docs. Add them, search them, and turn them into a study track."
        actions={<button disabled={!picked.length} onClick={() => navigate(`/tracks/from-materials?ids=${picked.join(',')}`)}>
          <Icon name="wand" size={16} />Build a track{picked.length ? ` from ${picked.length}` : ''}</button>} />
      {err && <ErrorBox>{err}</ErrorBox>}
      <div className="cols">
        <div>
          <div className="card">
            <div className="card-head"><h2>Your materials</h2>
              {ready.length > 0 && !picked.length && <span className="muted">Tick materials to build a track</span>}</div>
            {!items ? <Spinner /> : !items.length
              ? <Empty icon="book" title="Nothing uploaded yet">Add a textbook PDF, scanned notebook pages or Markdown notes.</Empty>
              : <div className="list">{items.map(m => {
                const working = PROCESSING.includes(m.status)
                return (
                  <div key={m.id} className="material">
                    <div className="item">
                      <div className="main">
                        <input type="checkbox" aria-label={`Use ${m.filename} for a track`} checked={picked.includes(m.id)}
                          disabled={m.status !== 'ready'} onChange={() => toggle(m.id)} />
                        <span className="file-ic"><Icon name={m.source_url ? 'globe' : 'file'} size={16} /></span>
                        <div style={{ minWidth: 0 }}>
                          <div className="title ellipsis">{m.source_url
                            ? <a href={m.source_url} target="_blank" rel="noreferrer noopener" title={m.source_url}>{m.filename}</a> : m.filename}</div>
                          <div className="muted">
                            <select className="type-select" aria-label={`Type of ${m.filename}`} value={m.source_type} disabled={working}
                              onChange={e => void setType(m, e.target.value as SourceType)}>
                              {(Object.keys(SOURCE_LABEL) as SourceType[]).map(t => <option key={t} value={t}>{SOURCE_LABEL[t]}</option>)}
                            </select>
                            {' · '}{m.source_url && m.web_pages ? `${m.web_pages} web page${m.web_pages === 1 ? '' : 's'} · ` : ''}{m.page_count} page{m.page_count === 1 ? '' : 's'}
                            {m.ocr_pages > 0 && ` · ${m.ocr_pages} read by OCR`}{m.status === 'ready' && ` · ${m.chunk_count} passages`}</div>
                        </div>
                      </div>
                      <div className="row" style={{ flexWrap: 'nowrap', gap: 6 }}>
                        {m.in_plan === false && m.status === 'ready' && (m.source_type === 'textbook' || m.source_type === 'notes') &&
                          <span className="badge yellow" title="No study track uses this yet. Ask the planner to add it.">Not in a plan</span>}
                        <span className={`badge ${tone(m.status)}`}>{working && <Spinner />}{STAGE[m.status] ?? m.status}</span>
                        {m.status === 'ready' && <button className="ghost sm" aria-expanded={open === m.id} onClick={() => setOpen(open === m.id ? null : m.id)} title="Outline"><Icon name="layers" size={14} /></button>}
                        {!working && <button className="ghost sm" onClick={() => reindex(m)} title={m.source_url ? 'Fetch the pages again' : 'Re-index'}><Icon name="refresh" size={14} /></button>}
                        <button className="ghost sm" onClick={() => remove(m)} title="Delete" aria-label={`Delete ${m.filename}`}><Icon name="trash" size={14} /></button>
                      </div>
                    </div>
                    {working && <ProgressBar value={m.progress} />}
                    {m.status === 'failed' && m.error && <div className="alert err-box"><Icon name="alert" size={16} />{m.error}</div>}
                    {open === m.id && <Outline id={m.id} />}
                  </div>)
              })}</div>}
          </div>
          <form className="card" onSubmit={ask}>
            <div className="card-head"><h2>Search your materials</h2></div>
            <div className="row" style={{ flexWrap: 'nowrap' }}>
              <input aria-label="Search" value={q} onChange={e => setQ(e.target.value)} placeholder="Ask about your material…" required />
              <button disabled={searching}>{searching ? <Spinner /> : <Icon name="arrow" size={16} />}Search</button></div>
            {res && <div style={{ marginTop: 18 }}>
              <span className={`badge ${res.is_grounded_in_notes ? 'green' : 'yellow'}`}>{res.badge}</span>
              <div style={{ marginTop: 12 }}><Markdown text={res.context_text} /></div>
              {res.sources.map((s, i) => <div key={i} className="source"><span>{s.citation}</span><span className="muted num">{Math.round(s.score * 100)}% match</span></div>)}</div>}
          </form>
        </div>
        <div>
          <div className="card">
            <div className="card-head"><h2>Add sources</h2></div>
            <label className={`drop ${over ? 'over' : ''}`} style={{ margin: 0 }}
              onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
              onDrop={e => { e.preventDefault(); setOver(false); void upload(e.dataTransfer.files) }}>
              {busy ? <Spinner /> : <Icon name="upload" size={24} />}
              <b>{busy ? `Uploading ${busy} file${busy > 1 ? 's' : ''}…` : 'Drop files or click to browse'}</b>
              <span className="muted">PDF textbooks, past exam papers, photos or scans of notebooks, .md, .txt, .ipynb</span>
              <input type="file" multiple accept={ACCEPT} disabled={!!busy} onChange={e => { void upload(e.target.files); e.target.value = '' }} />
            </label>
            <div className="or-divider"><span>or add a link</span></div>
            <form onSubmit={addLink}>
              <div className="row" style={{ flexWrap: 'nowrap' }}>
                <input aria-label="Link to a web page or docs" type="text" inputMode="url" value={link} onChange={e => setLink(e.target.value)}
                  placeholder="docs.python.org/3/tutorial/" required />
                <button disabled={adding || !link.trim()}>{adding ? <Spinner /> : <Icon name="globe" size={16} />}Add</button>
              </div>
              <label className="check-row"><input type="checkbox" checked={crawl} onChange={e => setCrawl(e.target.checked)} />
                <span>Include linked pages from the same docs section <span className="hint">(up to 15)</span></span></label>
            </form>
            <p className="muted" style={{ fontSize: 13, margin: '12px 0 0' }}>Works with docs sites, articles, public Google Docs and GitHub files. Each page becomes a chapter that links back to it. Everything you add is private to you.</p>
          </div>
          {storage && <div className="card">
            <div className="card-head"><h2>Storage</h2><span className="muted num">{storage.pages_used}{storage.unlimited ? '' : ` / ${storage.page_limit}`} pages</span></div>
            {!storage.unlimited && <ProgressBar value={(storage.pages_used / Math.max(1, storage.page_limit)) * 100} />}
            <p className="muted" style={{ fontSize: 13, margin: '10px 0 0' }}>
              {storage.unlimited ? 'No page limit on your account.' : `${Math.max(0, storage.page_limit - storage.pages_used)} pages left. Delete materials you no longer need to free space.`}</p>
          </div>}
        </div>
      </div>
    </>
  )
}
