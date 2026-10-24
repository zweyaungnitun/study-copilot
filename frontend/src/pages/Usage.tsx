import { api } from '../api'
import { DailyBars, QuotaMeter, RankBars, compact, featureLabel } from '../Charts'
import { useLoad } from '../hooks'
import { ErrorBox, Icon, PageHeader, ProgressRing, Skeleton } from '../ui'

const date = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: 'long', day: 'numeric' })

export default function Usage() {
  const { data, error, loading } = useLoad(() => api.myUsage(30), [])
  const head = <PageHeader title="AI usage" sub="Tokens your tutor, notes and other AI features used this month." />
  if (loading) return <>{head}<Skeleton lines={4} /></>
  if (error || !data) return <>{head}<ErrorBox>{error}</ErrorBox></>
  const q = data.quota
  const state = q.unlimited ? 'Unlimited plan' : q.percent >= 100 ? 'Limit reached' : q.percent >= 80 ? 'Running low' : 'Plenty left'

  return (
    <>
      {head}
      <section className="card quota-hero">
        <ProgressRing value={q.unlimited ? 0 : q.percent} size={104} stroke={10} tone={q.percent >= 100 ? 'spark' : 'accent'}
          label={q.unlimited ? 'Unlimited' : `${Math.round(q.percent)} percent of monthly tokens used`}>
          <b className="num">{q.unlimited ? '∞' : `${Math.round(q.percent)}%`}</b></ProgressRing>
        <div className="grow">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2 style={{ margin: 0 }}>{compact(q.used)} <span className="muted" style={{ fontWeight: 500 }}>/ {q.unlimited ? 'unlimited' : compact(q.limit)} tokens</span></h2>
            <span className={`badge ${q.unlimited || q.percent < 80 ? 'green' : q.percent < 100 ? 'yellow' : 'red'}`}>
              <Icon name={q.percent >= 80 && !q.unlimited ? 'alert' : 'check'} size={12} />{state}</span>
          </div>
          <QuotaMeter percent={q.percent} unlimited={q.unlimited} />
          <p className="muted" style={{ margin: 0 }}>
            {q.unlimited ? 'Your account has no monthly cap.' : <>{compact(q.remaining ?? 0)} tokens left · resets {date(q.resets_at)}</>}
            {q.custom_limit && ' · custom limit set by an admin'}</p>
          {!q.unlimited && q.percent >= 100 && <div className="alert err-box"><Icon name="alert" size={16} />AI features are paused until {date(q.resets_at)}. Ask an admin if you need more.</div>}
        </div>
      </section>

      <div className="cols">
        <div className="card"><div className="card-head"><h2>Last 30 days</h2></div><DailyBars data={data.daily} label="Daily tokens" /></div>
        <div className="card"><div className="card-head"><h2>By feature</h2><span className="muted">this month</span></div>
          <RankBars data={data.by_feature} format={featureLabel} empty="You haven't used any AI features this month." /></div>
      </div>
    </>
  )
}
