import { useCallback, useEffect, useState } from 'react'
import { admin, PROCESSING, utc, type AdminMaterial, type AdminMaterialsReport } from '../api'
import { ErrorBox, Icon, PageHeader, ProgressBar, Segmented, Skeleton, Spinner, useToast } from '../ui'
import { Stat, ago } from './shared'

type Filter = 'all' | 'processing' | 'failed' | 'ready'
const STATUS_TONE: Record<string, string> = { ready: 'green', failed: 'red' }
const mb = (b: number) => b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`

export default function AdminMaterials() {
  const toast = useToast()
  const [filter, setFilter] = useState<Filter>('all')
  const [data, setData] = useState<AdminMaterialsReport | null>(null)
  const [err, setErr] = useState('')
  const [limit, setLimit] = useState<string | null>(null)
  const [busy, setBusy] = useState('')

  const load = useCallback(() => admin.materials(filter === 'all' ? undefined : filter).then(d => { setData(d); setErr('') })
    .catch(e => setErr(e.message)), [filter])
  useEffect(() => { void load() }, [load])
  const processing = !!data?.materials.some(m => PROCESSING.includes(m.status))
  useEffect(() => {
    if (!processing) return
    const t = window.setInterval(() => void load(), 3000)
    return () => window.clearInterval(t)
  }, [processing, load])

  const act = async (id: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(id)
    try { await fn(); toast('ok', ok); await load() } catch (e) { toast('err', (e as Error).message) } finally { setBusy('') }
  }
  const saveLimit = async () => {
    const n = Math.max(0, Math.floor(Number(limit)))
    if (Number.isNaN(n)) return
    await act('limit', () => admin.setDefaultPageLimit(n), n ? `Default storage limit set to ${n} pages` : 'Storage limit removed (unlimited)')
    setLimit(null)
  }
  const remove = (m: AdminMaterial) => confirm(`Delete ${m.filename} (${m.username})? This removes the file, its outline, vectors and chapter links.`)
    && act(m.id, () => admin.deleteMaterial(m.id), `${m.filename} deleted`)

  const head = <PageHeader title="Materials" sub="Every upload, where it is in the pipeline, and storage limits."
    actions={<Segmented label="Filter" value={filter} onChange={setFilter}
      options={[['all', 'All'], ['processing', 'Processing'], ['failed', 'Failed'], ['ready', 'Ready']]} />} />
  if (!data && !err) return <>{head}<Skeleton lines={6} /></>
  const c = data?.counts ?? {}
  const working = PROCESSING.reduce((a, s) => a + (c[s] ?? 0), 0)

  return (
    <>
      {head}
      {err && <ErrorBox>{err}</ErrorBox>}
      {data && <>
        <div className="stats">
          <Stat icon="book" value={c.ready ?? 0} label="Ready" hint={<>{data.total_pages.toLocaleString()} pages stored</>} />
          <Stat icon="refresh" tone={working ? 'orange' : undefined} value={working} label="Processing" />
          <Stat icon="alert" tone={c.failed ? 'red' : 'green'} value={c.failed ?? 0} label="Failed" hint="retry or delete below" />
        </div>
        <div className="card">
          <div className="card-head"><div><h2>Default storage limit</h2>
            <p className="muted">Pages per user across all their materials (0 = unlimited). Override per user under Users & roles.</p></div></div>
          <form className="row" onSubmit={e => { e.preventDefault(); void saveLimit() }}>
            <input type="number" min={0} step={100} value={limit ?? String(data.default_page_limit)} onChange={e => setLimit(e.target.value)}
              aria-label="Default page limit" style={{ maxWidth: 180 }} />
            <span className="muted">pages / user</span>
            <button disabled={limit === null || busy === 'limit'}>{busy === 'limit' && <Spinner />}Save</button>
          </form>
        </div>
        <div className="card table-card"><table className="table">
          <thead><tr><th>File</th><th>Owner</th><th>Status</th><th className="r">Pages</th><th>Outline</th><th>Uploaded</th><th /></tr></thead>
          <tbody>{data.materials.map(m => (
            <tr key={m.id}>
              <td><b className="ellipsis" style={{ display: 'block', maxWidth: 260 }}>{m.filename}</b><span className="muted">{mb(m.file_size_bytes)}</span></td>
              <td>{m.username}</td>
              <td style={{ minWidth: 150 }}>
                <span className={`badge ${STATUS_TONE[m.status] ?? 'yellow'}`}>{PROCESSING.includes(m.status) && <Spinner />}{m.status}</span>
                {PROCESSING.includes(m.status) && <ProgressBar value={m.progress} />}
                {m.error && <div className="muted" style={{ fontSize: 12, marginTop: 4 }} title={m.error}>{m.error.slice(0, 90)}</div>}
              </td>
              <td className="r num">{m.page_count}{m.ocr_pages > 0 && <div className="muted">{m.ocr_pages} OCR</div>}</td>
              <td className="muted">{m.outline_source ?? '—'}</td>
              <td className="muted" title={utc(m.created_at).toLocaleString()}>{ago(m.created_at)}</td>
              <td><div className="row" style={{ flexWrap: 'nowrap', gap: 6 }}>
                {!PROCESSING.includes(m.status) && <button className="ghost sm" disabled={busy === m.id} title="Re-index"
                  onClick={() => act(m.id, () => admin.reindexMaterial(m.id), `Re-indexing ${m.filename}`)}><Icon name="refresh" size={14} /></button>}
                <button className="ghost sm" disabled={busy === m.id} title="Delete" aria-label={`Delete ${m.filename}`} onClick={() => remove(m)}><Icon name="trash" size={14} /></button>
              </div></td>
            </tr>))}
            {!data.materials.length && <tr><td colSpan={7} className="muted">No materials match.</td></tr>}</tbody>
        </table></div>
      </>}
    </>
  )
}
