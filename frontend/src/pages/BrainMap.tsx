import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type BrainMap, type BrainNode } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Empty, ErrorBox, PageHeader, ProgressRing, Segmented, Skeleton } from '../ui'

const COLORS: Record<string, string> = { green: 'var(--green)', yellow: 'var(--yellow)', red: 'var(--red)', gray: 'var(--gray)' }
const LEGEND: [string, string][] = [['green', 'Mastered'], ['yellow', 'Shaky'], ['red', 'At risk'], ['gray', 'Locked']]

/** Layered layout (by longest prerequisite chain) of one brain map. Clicking a topic opens its chapter. */
function Graph({ data }: { data: BrainMap }) {
  const nav = useNavigate()
  const depth: Record<string, number> = {}
  const parents = (id: string) => data.edges.filter(e => e.target === id).map(e => e.source)
  const d = (id: string, seen = new Set<string>()): number => {
    if (depth[id] !== undefined) return depth[id]
    if (seen.has(id)) return 0
    seen.add(id)
    return (depth[id] = Math.max(-1, ...parents(id).map(p => d(p, seen))) + 1)
  }
  data.nodes.forEach(n => d(n.id))
  const layers: BrainNode[][] = []
  data.nodes.forEach(n => (layers[depth[n.id]] ??= []).push(n))
  const pos: Record<string, [number, number]> = {}
  layers.forEach((L, x) => L?.forEach((n, y) => (pos[n.id] = [60 + x * 170, 40 + y * 70])))
  const w = 120 + layers.length * 170, h = 80 + Math.max(1, ...layers.map(l => l?.length || 0)) * 70
  return (
    <div className="map-wrap">
      <svg width={w} height={h} role="img" aria-label="Topic dependency graph">
        {data.edges.map((e, i) => pos[e.source] && pos[e.target] &&
          <line key={i} x1={pos[e.source][0]} y1={pos[e.source][1]} x2={pos[e.target][0]} y2={pos[e.target][1]} stroke="var(--line-strong)" strokeWidth={2} strokeLinecap="round" />)}
        {data.nodes.map(n => (
          <g key={n.id} className="node" tabIndex={0} role="link" aria-label={`${n.label}, ${n.status}. Open chapter`} style={{ cursor: 'pointer' }}
            transform={`translate(${pos[n.id][0]},${pos[n.id][1]})`} onClick={() => nav(`/chapters/${n.id}`)} onKeyDown={e => e.key === 'Enter' && nav(`/chapters/${n.id}`)}>
            <circle r={18} fill={n.color.startsWith('#') ? n.color : COLORS[n.color] ?? COLORS.gray} stroke="var(--surface)" strokeWidth={3}>
              <title>{`${n.track ? n.track + ' · ' : ''}${n.label}: ${n.status}, retention ${Math.round(n.retention_score * 100)}%`}</title></circle>
            <text y={36} textAnchor="middle" fontSize={11.5} fontWeight={500} fill="var(--text-2)">{n.label.length > 22 ? n.label.slice(0, 21) + '…' : n.label}</text>
          </g>))}
      </svg>
    </div>
  )
}

/** One brain map with its own stats and legend. */
function MapPanel({ title, data, to }: { title: string; data: BrainMap; to?: string }) {
  const ret = Math.round(data.overall_retention_average * 100)
  return (
    <section className="card map-panel" aria-label={`Brain map: ${title}`}>
      <div className="card-head">
        <div className="row" style={{ gap: 14, flexWrap: 'nowrap' }}>
          <ProgressRing value={ret} size={48} stroke={5} tone={data.at_risk_count ? 'spark' : 'green'} label={`Average retention ${ret} percent`}><b className="num" style={{ fontSize: 12 }}>{ret}%</b></ProgressRing>
          <div><h2 style={{ margin: 0 }}>{title}</h2>
            <p className="muted" style={{ margin: 0 }}>{data.total_nodes} topics · {data.at_risk_count} at risk · {ret}% avg retention</p></div></div>
        {to && <Link to={to} className="muted">Open track</Link>}
      </div>
      {data.total_nodes ? <Graph data={data} /> : <p className="muted">No topics yet.</p>}
      <div className="legend">{LEGEND.map(([c, l]) => <span key={c}><i className={`dot ${c}`} />{l}</span>)}</div>
    </section>
  )
}

export default function BrainMapPage() {
  const { session } = useAuth()
  const uid = session!.user_id
  // 'each' = one brain map per track, a track id = just that track, 'combined' = all topics in one graph
  const [view, setView] = useState('each')
  const tracks = useLoad(() => api.tracks(uid).catch(() => []), [uid])
  const list = tracks.data ?? []
  const maps = useLoad(async () => {
    if (!tracks.data?.length) return []
    if (view === 'combined') return [{ id: 'all', title: 'All tracks combined', map: await api.brainMap(uid) }]
    const wanted = view === 'each' ? tracks.data : tracks.data.filter(t => t.id === view)
    return Promise.all(wanted.map(async t => ({ id: t.id, title: t.specialization, map: await api.brainMap(uid, t.id) })))
  }, [uid, view, tracks.data])

  const head = <PageHeader title="Brain Map" sub="How well you remember each topic, and how topics connect. Click a topic to open it." />
  if (tracks.loading || (maps.loading && !maps.data)) return <>{head}<Skeleton lines={5} /></>
  if (!list.length) return <>{head}<Empty icon="brain" title="No brain map yet" action={<Link to="/onboarding"><button>Create a roadmap</button></Link>}>
    Your brain map is built from your tracks. Create one to start tracking retention.</Empty></>
  if (maps.error) return <>{head}<ErrorBox>{maps.error}</ErrorBox></>

  const options: [string, string][] = list.length > 1
    ? [['each', 'Each track'], ...list.map(t => [t.id, t.specialization] as [string, string]), ['combined', 'Combined']]
    : []
  const data = maps.data ?? []
  const totals = data.reduce((a, m) => ({ topics: a.topics + m.map.total_nodes, risk: a.risk + m.map.at_risk_count }), { topics: 0, risk: 0 })
  return (
    <>
      {head}
      {options.length > 0 && <div style={{ marginBottom: 16 }}><Segmented label="Brain map view" value={view} onChange={setView} options={options} /></div>}
      {data.length > 1 && <p className="muted" style={{ marginBottom: 12 }}>{data.length} brain maps · {totals.topics} topics · {totals.risk} at risk</p>}
      <div className="map-stack" aria-busy={maps.loading}>
        {data.map(m => <MapPanel key={m.id} title={m.title} data={m.map} to={view === 'each' ? `/roadmap?track=${m.id}` : undefined} />)}
      </div>
    </>
  )
}
