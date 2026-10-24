import { useState } from 'react'
import { admin, utc, type AdminUser } from '../api'
import { DailyBars, QuotaMeter, RankBars, compact, featureLabel } from '../Charts'
import { useLoad } from '../hooks'
import { ErrorBox, Icon, PageHeader, Segmented, Skeleton, Spinner, useToast } from '../ui'
import { Stat } from './shared'

/** Inline editor for one user's monthly limit: custom number, unlimited (0) or inherit the default (null). */
function LimitEditor({ user, onSaved }: { user: AdminUser; onSaved: (u: AdminUser) => void }) {
  const toast = useToast()
  const [value, setValue] = useState(user.custom_limit ? String(user.token_limit) : '')
  const [busy, setBusy] = useState(false)
  const save = async (limit: number | null) => {
    setBusy(true)
    try { const u = await admin.updateUser(user.id, { token_limit: limit }); onSaved(u); setValue(u.custom_limit ? String(u.token_limit) : ''); toast('ok', `Limit updated for ${u.username}`) }
    catch (e) { toast('err', (e as Error).message) } finally { setBusy(false) }
  }
  const parsed = value.trim() === '' ? null : Math.max(0, Math.floor(Number(value)))
  return (
    <form className="limit-editor" onSubmit={e => { e.preventDefault(); if (parsed !== null && !Number.isNaN(parsed)) void save(parsed) }}>
      <input type="number" min={0} step={10000} value={value} onChange={e => setValue(e.target.value)} placeholder="Default"
        aria-label={`Monthly token limit for ${user.username}`} />
      <button className="sm" disabled={busy || parsed === null || Number.isNaN(parsed)}>Set</button>
      {user.custom_limit && <button type="button" className="ghost sm" disabled={busy} onClick={() => save(null)} title="Use the platform default">Reset</button>}
      {busy && <Spinner />}
    </form>
  )
}

export default function AdminTokens() {
  const toast = useToast()
  const [days, setDays] = useState(30)
  const { data, error, loading, setData } = useLoad(() => admin.tokens(days), [days])
  const [def, setDef] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [q, setQ] = useState('')
  const head = <PageHeader title="Token management" sub="Monthly AI token budgets per user, and where the tokens go."
    actions={<Segmented label="Range" value={days} onChange={setDays} options={[[14, '14d'], [30, '30d'], [90, '90d']]} />} />
  if (loading && !data) return <>{head}<Skeleton lines={6} /></>
  if (error || !data) return <>{head}<ErrorBox>{error}</ErrorBox></>

  const defValue = def ?? String(data.default_monthly_limit)
  const saveDefault = async () => {
    const n = Math.max(0, Math.floor(Number(defValue)))
    if (Number.isNaN(n)) return
    setSaving(true)
    try {
      await admin.setDefaultLimit(n)
      setData(await admin.tokens(days)); setDef(null)
      toast('ok', n ? `Default limit set to ${n.toLocaleString()} tokens` : 'Default limit removed (unlimited)')
    } catch (e) { toast('err', (e as Error).message) } finally { setSaving(false) }
  }
  const updateRow = (u: AdminUser) => setData({ ...data, users: data.users.map(x => x.id === u.id ? u : x) })
  const over = data.users.filter(u => u.token_limit && u.tokens_used >= u.token_limit).length
  const users = data.users.filter(u => !q || u.username.toLowerCase().includes(q.toLowerCase()))

  return (
    <>
      {head}
      <div className="stats">
        <Stat icon="coins" value={compact(data.total_tokens)} label="Tokens this month" hint={<>{data.total_calls.toLocaleString()} model calls</>} />
        <Stat icon="alert" tone={over ? 'red' : 'green'} value={over} label="Users at their limit" />
        <Stat icon="clock" value={utc(data.resets_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} label="Quotas reset"
          hint={<>period began {utc(data.period_start).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</>} />
        <Stat icon="users" value={compact(data.unattributed_tokens)} label="Unattributed tokens" hint="calls without a signed-in user" />
      </div>

      <div className="card">
        <div className="card-head"><div><h2>Default monthly limit</h2>
          <p className="muted">Applies to every user without a custom limit. 0 means unlimited. Over-limit users get a clear error instead of AI responses until the 1st.</p></div></div>
        <form className="row" onSubmit={e => { e.preventDefault(); void saveDefault() }}>
          <input type="number" min={0} step={50000} value={defValue} onChange={e => setDef(e.target.value)} aria-label="Default monthly token limit" style={{ maxWidth: 220 }} />
          <span className="muted">tokens / user / month</span>
          <button disabled={saving || def === null}>{saving && <Spinner />}Save default</button>
        </form>
      </div>

      <div className="card"><div className="card-head"><h2>Daily tokens</h2><span className="muted">all users · last {days} days</span></div>
        <DailyBars data={data.daily} label="Platform tokens per day" /></div>

      <div className="cols">
        <div className="card"><div className="card-head"><h2>By feature</h2><span className="muted">this month</span></div>
          <RankBars data={data.by_feature} format={featureLabel} /></div>
        <div className="card"><div className="card-head"><h2>By model</h2><span className="muted">this month</span></div>
          <RankBars data={data.by_model} /></div>
      </div>

      <div className="card table-card">
        <div className="card-head" style={{ padding: '20px 20px 0' }}><h2>Per-user budgets</h2>
          <div className="table-search"><Icon name="search" size={16} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Filter users" aria-label="Filter users" /></div></div>
        <table className="table">
          <thead><tr><th>User</th><th>Used this month</th><th>Limit</th><th>Set custom limit</th></tr></thead>
          <tbody>{users.map(u => (
            <tr key={u.id}>
              <td><b>{u.username}</b>{u.role === 'admin' && <span className="badge" style={{ marginLeft: 6 }}>admin</span>}</td>
              <td style={{ minWidth: 180 }}>
                <div className="row" style={{ justifyContent: 'space-between', gap: 6 }}><span className="num">{compact(u.tokens_used)}</span>
                  <span className="muted num">{u.token_limit ? `${Math.round(u.percent)}%` : '—'}</span></div>
                <QuotaMeter percent={u.percent} unlimited={!u.token_limit} /></td>
              <td className="num">{u.token_limit ? compact(u.token_limit) : 'Unlimited'}<div className="muted">{u.custom_limit ? 'custom' : 'default'}</div></td>
              <td><LimitEditor user={u} onSaved={updateRow} /></td>
            </tr>))}</tbody>
        </table>
      </div>
    </>
  )
}
