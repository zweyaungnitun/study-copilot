import { Link } from 'react-router-dom'
import { admin } from '../api'
import { DailyBars, QuotaMeter, compact } from '../Charts'
import { useLoad } from '../hooks'
import { ErrorBox, Icon, PageHeader, Skeleton } from '../ui'
import { RiskBadge, Stat, ago } from './shared'

export default function AdminOverview() {
  const { data, error, loading } = useLoad(() => admin.overview(), [])
  const head = <PageHeader title="Admin dashboard" sub="Platform health, exam integrity and AI spend at a glance." />
  if (loading) return <>{head}<Skeleton lines={5} /></>
  if (error || !data) return <>{head}<ErrorBox>{error}</ErrorBox></>
  const s = data.stats

  return (
    <>
      {head}
      <div className="stats">
        <Stat icon="users" value={s.total_users} label="Users" hint={<>{s.active_users_7d} active · {s.new_users_7d} new this week</>} />
        <Stat icon="shield" tone={s.exams_flagged_unreviewed ? 'orange' : 'green'} value={s.exams_live} label="Exams live now"
          hint={<>{s.exams_flagged_unreviewed} awaiting review · {s.exams_total} total</>} />
        <Stat icon="coins" value={compact(s.tokens_this_period)} label="Tokens this month" hint={<>{compact(s.tokens_today)} today</>} />
        <Stat icon="alert" tone={s.users_over_quota ? 'red' : 'green'} value={s.users_over_quota} label="Users at token limit"
          hint={<>{s.users_near_quota} above 80% · default {s.default_token_limit ? compact(s.default_token_limit) : 'unlimited'}</>} />
      </div>

      <div className="cols">
        <div className="card">
          <div className="card-head"><h2>Token usage · 14 days</h2><Link to="/admin/tokens" className="muted">Manage tokens</Link></div>
          <DailyBars data={data.daily_tokens} label="Platform tokens per day" />
        </div>
        <div className="card">
          <div className="card-head"><h2>Top consumers</h2><span className="muted">this month</span></div>
          {!data.top_consumers.length ? <p className="muted">No AI usage recorded this month.</p> : (
            <div>{data.top_consumers.map(u => (
              <div className="consumer" key={u.id}>
                <div className="row" style={{ justifyContent: 'space-between' }}><b>{u.username}</b>
                  <span className="num muted">{compact(u.tokens_used)} / {u.token_limit ? compact(u.token_limit) : '∞'}</span></div>
                <QuotaMeter percent={u.percent} unlimited={!u.token_limit} />
              </div>))}</div>)}
        </div>
      </div>

      <div className="cols">
        <div className="card">
          <div className="card-head"><h2><span className="live-dot" /> Live exams</h2><Link to="/admin/proctoring" className="muted">Open proctoring</Link></div>
          {!data.live_exams.length ? <p className="muted">Nobody is sitting an exam right now.</p> : (
            <div className="list">{data.live_exams.map(a => (
              <Link to={`/admin/proctoring?attempt=${a.id}`} className="item linklike" key={a.id}>
                <div className="main"><div><div className="title">{a.username}</div><div className="muted">started {ago(a.started_at)} · {a.flag_count} flags</div></div></div>
                <RiskBadge risk={a.risk} score={a.integrity_score} /></Link>))}</div>)}
        </div>
        <div className="card">
          <div className="card-head"><h2>Needs review</h2>{s.avg_integrity_30d !== null && <span className="muted">avg integrity {s.avg_integrity_30d}</span>}</div>
          {!data.recent_flagged.length ? <p className="muted"><Icon name="check" size={14} /> No flagged attempts waiting.</p> : (
            <div className="list">{data.recent_flagged.map(a => (
              <Link to={`/admin/proctoring?attempt=${a.id}`} className="item linklike" key={a.id}>
                <div className="main"><div><div className="title">{a.username}</div><div className="muted">{ago(a.started_at)} · {a.flag_count} flags</div></div></div>
                <RiskBadge risk={a.risk} score={a.integrity_score} /></Link>))}</div>)}
        </div>
      </div>
    </>
  )
}
