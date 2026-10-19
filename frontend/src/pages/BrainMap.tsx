import { api, type BrainNode } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { ErrorBox, PageHeader, Skeleton } from '../ui'

const COLORS: Record<string, string> = { green: 'var(--green)', yellow: 'var(--yellow)', red: 'var(--red)', gray: 'var(--gray)' }

export default function BrainMapPage() {
  const { session } = useAuth()
  const { data, error, loading } = useLoad(() => api.brainMap(session!.user_id), [])
  const head = (sub?: string) => <PageHeader title="Brain Map" sub={sub} />
  if (loading) return <>{head()}<Skeleton lines={5} /></>
  if (error || !data) return <>{head()}<ErrorBox>{error}</ErrorBox></>

  // layered layout by longest prerequisite depth
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

  const stats: [string, string][] = [['Topics', String(data.total_nodes)], ['Avg retention', `${Math.round(data.overall_retention_average * 100)}%`], ['At risk', String(data.at_risk_count)]]
  return (
    <>
      {head('How well you remember each topic, and how topics connect.')}
      <div className="stats">{stats.map(([l, v]) => <div className="card" key={l}><div><div className="stat">{v}</div><div className="stat-label">{l}</div></div></div>)}</div>
      <div className="card">
        <div className="map-wrap">
          <svg width={w} height={h} role="img" aria-label="Topic dependency graph">
            {data.edges.map((e, i) => pos[e.source] && pos[e.target] &&
              <line key={i} x1={pos[e.source][0]} y1={pos[e.source][1]} x2={pos[e.target][0]} y2={pos[e.target][1]} stroke="var(--line-strong)" strokeWidth={2} strokeLinecap="round" />)}
            {data.nodes.map(n => (
              <g key={n.id} className="node" transform={`translate(${pos[n.id][0]},${pos[n.id][1]})`}>
                <circle r={18} fill={n.color.startsWith('#') ? n.color : COLORS[n.color] ?? COLORS.gray} stroke="var(--surface)" strokeWidth={3}><title>{`${n.label}: ${n.status}, retention ${Math.round(n.retention_score * 100)}%`}</title></circle>
                <text y={36} textAnchor="middle" fontSize={11.5} fontWeight={500} fill="var(--text-2)">{n.label.length > 22 ? n.label.slice(0, 21) + '…' : n.label}</text>
              </g>))}
          </svg>
        </div>
        <div className="legend">{(['green', 'yellow', 'red', 'gray'] as const).map((c, i) => <span key={c}><i className={`dot ${c}`} />{['Mastered', 'Shaky', 'At risk', 'Locked'][i]}</span>)}</div>
      </div>
    </>
  )
}
