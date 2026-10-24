import { useState } from 'react'
import type { DailyUsage, UsageSlice } from './api'

/** 12345 -> "12.3k", 2500000 -> "2.5M". */
export const compact = (n: number) =>
  n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${+(n / 1e3).toFixed(1)}k` : String(n)

const day = (iso: string) => new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

/** Single-series daily token columns: hover tooltip per bar, recessive grid, table view for screen readers. */
export function DailyBars({ data, label, height = 180 }: { data: DailyUsage[]; label: string; height?: number }) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...data.map(d => d.tokens))
  const W = 600, H = height, padB = 22, padT = 8
  const slot = W / Math.max(1, data.length)
  const bw = Math.max(2, slot - 2)  // 2px surface gap between adjacent bars
  const y = (v: number) => H - padB - (v / max) * (H - padB - padT)
  const ticks = [0.5, 1].map(f => Math.round(max * f))
  const every = Math.ceil(data.length / 7)
  const total = data.reduce((a, d) => a + d.tokens, 0)
  const h = hover !== null ? data[hover] : null

  return (
    <figure className="chart">
      <div className="chart-plot" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
          aria-label={`${label}: ${compact(total)} tokens over ${data.length} days, peak ${compact(max)}`}>
          {ticks.map(t => <line key={t} className="chart-grid" x1={0} x2={W} y1={y(t)} y2={y(t)} />)}
          <line className="chart-axis" x1={0} x2={W} y1={H - padB} y2={H - padB} />
          {data.map((d, i) => {
            const top = y(d.tokens), x = i * slot + 1, base = H - padB
            const r = Math.min(4, bw / 2, base - top)  // rounded data-end, square at the baseline
            return (
              <g key={d.date} onMouseEnter={() => setHover(i)}>
                <rect className="chart-hit" x={i * slot} y={0} width={slot} height={base} />
                {d.tokens > 0 && <path className={`chart-bar ${hover === i ? 'on' : ''}`}
                  d={`M${x},${base}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${base}Z`} />}
              </g>)
          })}
        </svg>
        <div className="chart-yticks" aria-hidden="true">{ticks.slice().reverse().map(t => <span key={t} style={{ top: `${(y(t) / H) * 100}%` }}>{compact(t)}</span>)}</div>
        <div className="chart-xticks" aria-hidden="true">{data.map((d, i) => i % every === 0 &&
          <span key={d.date} style={{ left: `${((i + 0.5) / data.length) * 100}%` }}>{day(d.date)}</span>)}</div>
        {h && <div className="chart-tip" style={{ left: `${((hover! + 0.5) / data.length) * 100}%` }}>
          <b>{day(h.date)}</b><span className="num">{h.tokens.toLocaleString()} tokens</span><span className="muted">{h.calls} calls</span></div>}
      </div>
      <details className="chart-table"><summary>View as table</summary>
        <table className="table"><thead><tr><th>Date</th><th className="r">Tokens</th><th className="r">Calls</th></tr></thead>
          <tbody>{data.map(d => <tr key={d.date}><td>{day(d.date)}</td><td className="r num">{d.tokens.toLocaleString()}</td><td className="r num">{d.calls}</td></tr>)}</tbody></table>
      </details>
    </figure>
  )
}

/** Ranked horizontal bars (magnitude, one hue) with the value as text beside each bar. */
export function RankBars({ data, empty = 'No usage yet', format = (k: string) => k }: {
  data: UsageSlice[]; empty?: string; format?: (key: string) => string
}) {
  if (!data.length) return <p className="muted">{empty}</p>
  const max = Math.max(1, ...data.map(d => d.tokens))
  const total = data.reduce((a, d) => a + d.tokens, 0) || 1
  return (
    <ul className="rank-bars">
      {data.map(d => (
        <li key={d.key} title={`${d.tokens.toLocaleString()} tokens · ${d.calls} calls`}>
          <span className="rb-label">{format(d.key)}</span>
          <span className="rb-track"><i style={{ width: `${(d.tokens / max) * 100}%` }} /></span>
          <span className="rb-value num">{compact(d.tokens)} <span className="muted">{Math.round((d.tokens / total) * 100)}%</span></span>
        </li>))}
    </ul>
  )
}

/** Quota meter that turns warning/critical as it fills; state is also spelled out in text. */
export function QuotaMeter({ percent, unlimited }: { percent: number; unlimited?: boolean }) {
  const tone = unlimited ? 'ok' : percent >= 100 ? 'crit' : percent >= 80 ? 'warn' : 'ok'
  return <div className={`quota-meter ${tone}`} role="progressbar" aria-valuenow={unlimited ? 0 : Math.round(percent)} aria-valuemin={0} aria-valuemax={100}>
    <i style={{ width: `${unlimited ? 0 : Math.min(100, percent)}%` }} /></div>
}

export const FEATURE_LABELS: Record<string, string> = {
  tutor: 'AI tutor', roadmap: 'Roadmaps', chapters: 'Notes & guides', flashcards: 'Flashcards', materials: 'Library (embeddings)',
  intake: 'Diagnostics', coach: 'Coach reports', exam: 'Exams', mistakes: 'Mistakes', chats: 'Chats', other: 'Other', background: 'Background jobs',
}
export const featureLabel = (k: string) => FEATURE_LABELS[k] ?? k
