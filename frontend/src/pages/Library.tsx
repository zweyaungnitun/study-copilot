import { useState, type FormEvent } from 'react'
import { api, type RAGResult } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Empty, ErrorBox, Icon, Markdown, PageHeader, Spinner, useToast } from '../ui'

const tone: Record<string, string> = { ready: 'green', completed: 'green', processing: 'yellow', failed: 'red' }

export default function Library() {
  const { session } = useAuth()
  const toast = useToast()
  const uid = session!.user_id
  const { data, setData, loading } = useLoad(() => api.materials(uid), [uid])
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  const [searching, setSearching] = useState(false)
  const [res, setRes] = useState<RAGResult | null>(null)

  const upload = async (f?: File) => {
    if (!f) return
    setBusy(true); setErr('')
    try { await api.upload(uid, f); setData(await api.materials(uid)); toast('ok', `${f.name} added`) }
    catch (e) { toast('err', (e as Error).message) } finally { setBusy(false) }
  }
  const ask = async (e: FormEvent) => {
    e.preventDefault(); setSearching(true)
    try { setRes(await api.queryMaterials(uid, q)); setErr('') } catch (x) { setErr((x as Error).message) } finally { setSearching(false) }
  }
  return (
    <>
      <PageHeader title="Library" sub="Upload your notes and search them with citations." />
      <div className="cols">
        <div>
          <form className="card" onSubmit={ask}>
            <div className="card-head"><h2>Search your notes</h2></div>
            <div className="row" style={{ flexWrap: 'nowrap' }}>
              <input aria-label="Search" value={q} onChange={e => setQ(e.target.value)} placeholder="Ask about your material…" required />
              <button disabled={searching}>{searching ? <Spinner /> : <Icon name="arrow" size={16} />}Search</button></div>
            {err && <ErrorBox>{err}</ErrorBox>}
            {res && <div style={{ marginTop: 18 }}>
              <span className={`badge ${res.is_grounded_in_notes ? 'green' : 'yellow'}`}>{res.badge}</span>
              <div style={{ marginTop: 12 }}><Markdown text={res.context_text} /></div>
              {res.sources.map((s, i) => <div key={i} className="source"><span>{s.citation}</span><span className="muted num">{Math.round(s.score * 100)}% match</span></div>)}</div>}
          </form>
        </div>
        <div>
          <div className="card">
            <div className="card-head"><h2>Upload notes</h2></div>
            <label className={`drop ${over ? 'over' : ''}`} style={{ margin: 0 }}
              onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
              onDrop={e => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]) }}>
              {busy ? <Spinner /> : <Icon name="upload" size={24} />}
              <b>{busy ? 'Ingesting…' : 'Drop a file or click to browse'}</b>
              <span className="muted">PDF, TXT, MD or DOCX</span>
              <input type="file" accept=".pdf,.txt,.md,.docx" disabled={busy} onChange={e => { upload(e.target.files?.[0]); e.target.value = '' }} />
            </label>
          </div>
          <div className="card">
            <div className="card-head"><h2>Your files</h2>{!!data?.length && <span className="muted">{data.length}</span>}</div>
            {loading ? <div className="skeleton" /> : data?.length ? <div className="list">{data.map(m => (
              <div className="item" key={m.id}><div className="main"><span className="file-ic"><Icon name="file" size={16} /></span>
                <div><div className="title">{m.filename}</div><div className="muted">{m.chunk_count} chunks</div></div></div>
                <span className={`badge ${tone[m.status] ?? 'gray'}`}>{m.status}</span></div>))}</div>
              : <Empty icon="file" title="Nothing uploaded yet">Add notes to search them.</Empty>}
          </div>
        </div>
      </div>
    </>
  )
}
