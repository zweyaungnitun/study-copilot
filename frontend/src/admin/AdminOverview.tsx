import { Link } from 'react-router-dom'
import { admin } from '../api'
import { useAuth } from '../auth'
import { DailyBars, QuotaMeter, compact } from '../Charts'
import { useLoad } from '../hooks'
import { CountUp, ErrorBox, HeroGlow, Icon, PageHeader, ProgressRing, RevealText, Skeleton, spotlight, tileGlow, type IconName } from '../ui'
import { RiskBadge, ago } from './shared'

export default function AdminOverview() {
  const { session } = useAuth()
  const { data, error, loading } = useLoad(() => admin.overview(), [])
  const head = <PageHeader title="Admin dashboard" sub="Platform health, exam integrity and AI spend at a glance." />
  if (loading) return <>{head}<Skeleton lines={5} /></>
  if (error || !data) return <>{head}<ErrorBox>{error}</ErrorBox></>
  const s = data.stats

  const hour = new Date().getHours()
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const todayLabel = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
  const review = s.exams_flagged_unreviewed
  const status = review ? `${review} flagged exam${review > 1 ? 's' : ''} waiting for review.`
    : s.users_over_quota ? `${s.users_over_quota} user${s.users_over_quota > 1 ? 's have' : ' has'} hit the token limit.`
      : 'All quiet. No flagged exams and nobody at their token limit.'
  const integrity = s.avg_integrity_30d
  // [icon, tone, value, label, hint, formatter]
  const kpis: [IconName, string, number, string, string, ((n: number) => string)?][] = [
    ['users', 'violet', s.total_users, 'users', `${s.active_users_7d} active · ${s.new_users_7d} new this week`],
    ['shield', review ? 'peach' : 'mint', s.exams_total, 'exams taken', `${review} awaiting review`],
    ['coins', 'sky', s.tokens_this_period, 'tokens this month', `${compact(s.tokens_today)} today`, compact],
    ['alert', s.users_over_quota ? 'rose' : 'mint', s.users_over_quota, 'at token limit',
      `${s.users_near_quota} above 80% · default ${s.default_token_limit ? compact(s.default_token_limit) : 'unlimited'}`],
  ]

  return (
    <div className="bento" onPointerMove={tileGlow}>
      <section className="tile tile-hero span-8" aria-label="Platform status" onPointerMove={spotlight}>
        <HeroGlow />
        <span className="tile-eyebrow">{todayLabel}</span>
        <h1><RevealText text={`${greet}, ${session!.username}`} delay={0.15} /></h1>
        <p>{status}</p>
        <div className="hero-chips">
          <span className="hero-pill">{s.exams_live > 0 && <i className="live-dot" aria-hidden="true" />}<b className="num"><CountUp value={s.exams_live} /></b> live exam{s.exams_live === 1 ? '' : 's'}</span>
          <span className="hero-pill"><b className="num"><CountUp value={s.active_users_7d} /></b> active this week</span>
          <span className="hero-pill"><b className="num"><CountUp value={s.tokens_today} format={compact} /></b> tokens today</span>
        </div>
        <div className="row">
          <Link to="/admin/proctoring"><button className="btn-light lg"><Icon name="shield" size={16} />{review ? 'Review flagged exams' : 'Open proctoring'}<Icon name="arrow" size={16} /></button></Link>
          <Link to="/admin/tokens"><button className="btn-outline-light lg"><Icon name="coins" size={16} />Manage tokens</button></Link>
        </div>
      </section>

      <section className="tile span-4 tile-mastery" aria-label="Exam integrity">
        <ProgressRing value={integrity ?? 0} size={148} stroke={16} tone={integrity === null || integrity >= 80 ? 'green' : 'accent'}
          label={integrity === null ? 'No integrity data yet' : `Average integrity ${integrity} out of 100`}>
          <b className="num">{integrity === null ? '–' : <CountUp value={Math.round(integrity)} />}</b></ProgressRing>
        <b className="tile-title">Exam integrity</b>
        <span className="muted">{integrity === null ? 'No finished exams in the last 30 days' : '30-day average across all attempts'}</span>
      </section>

      {kpis.map(([ic, tone, v, label, hint, fmt]) => (
        <div key={label} className={`tile tile-stat span-3 tone-${tone}`}>
          <span className="tile-icon"><Icon name={ic} size={18} /></span>
          <b className="num"><CountUp value={v} format={fmt} /></b><span>{label}</span>
          <span className="tile-stat-hint">{hint}</span>
        </div>))}

      <section className="tile span-8" aria-label="Token usage">
        <div className="tile-head"><h2>Token usage · 14 days</h2><Link to="/admin/tokens" className="tile-link">Manage tokens</Link></div>
        <DailyBars data={data.daily_tokens} label="Platform tokens per day" />
      </section>

      <section className="tile span-4" aria-label="Top consumers">
        <div className="tile-head"><h2>Top consumers</h2><span className="muted">this month</span></div>
        {!data.top_consumers.length ? <p className="muted">No AI usage recorded this month.</p> : (
          <ol className="consumers">{data.top_consumers.map((u, i) => (
            <li key={u.id} style={{ animationDelay: `${0.3 + i * 0.05}s` }}>
              <span className="consumer-rank num">{i + 1}</span>
              <div className="grow">
                <div className="consumer-line"><b>{u.username}</b>
                  <span className="num muted">{compact(u.tokens_used)} / {u.token_limit ? compact(u.token_limit) : '∞'}</span></div>
                <QuotaMeter percent={u.percent} unlimited={!u.token_limit} />
              </div>
            </li>))}</ol>)}
      </section>

      <section className="tile span-6" aria-label="Live exams">
        <div className="tile-head"><h2>Live exams{s.exams_live > 0 && <i className="live-dot" aria-hidden="true" />}</h2><Link to="/admin/proctoring" className="tile-link">Open proctoring</Link></div>
        {!data.live_exams.length ? <div className="tile-quiet"><Icon name="eye" size={18} /><span>Nobody is sitting an exam right now.</span></div> : (
          <div className="list">{data.live_exams.map(a => (
            <Link to={`/admin/proctoring?attempt=${a.id}`} className="item linklike" key={a.id}>
              <div className="main"><div><div className="title">{a.username}</div><div className="muted">started {ago(a.started_at)} · {a.flag_count} flags</div></div></div>
              <RiskBadge risk={a.risk} score={a.integrity_score} /></Link>))}</div>)}
      </section>

      <section className="tile span-6" aria-label="Needs review">
        <div className="tile-head"><h2>Needs review</h2>{review > 0 && <span className="badge yellow">{review} waiting</span>}</div>
        {!data.recent_flagged.length ? <div className="tile-quiet ok"><Icon name="check" size={18} /><span>No flagged attempts waiting.</span></div> : (
          <div className="list">{data.recent_flagged.map(a => (
            <Link to={`/admin/proctoring?attempt=${a.id}`} className="item linklike" key={a.id}>
              <div className="main"><div><div className="title">{a.username}</div><div className="muted">{ago(a.started_at)} · {a.flag_count} flags</div></div></div>
              <RiskBadge risk={a.risk} score={a.integrity_score} /></Link>))}</div>)}
      </section>
    </div>
  )
}
