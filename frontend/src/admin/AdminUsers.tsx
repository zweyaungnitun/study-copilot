import { useEffect, useState } from 'react'
import { Spinner } from '../ui'
import { admin, utc, type AdminUser } from '../api'
import { useAuth } from '../auth'
import { compact } from '../Charts'
import { ErrorBox, Icon, PageHeader, Skeleton, useToast } from '../ui'

/** Storage cap in pages: a number overrides the platform default (0 = unlimited); Reset inherits it again. */
function PageLimit({ user, onSaved }: { user: AdminUser; onSaved: (u: AdminUser) => void }) {
  const toast = useToast()
  const [value, setValue] = useState(user.custom_page_limit ? String(user.page_limit) : '')
  const [busy, setBusy] = useState(false)
  const save = async (limit: number | null) => {
    setBusy(true)
    try { const u = await admin.updateUser(user.id, { storage_page_limit: limit }); onSaved(u); setValue(u.custom_page_limit ? String(u.page_limit) : '') }
    catch (e) { toast('err', (e as Error).message) } finally { setBusy(false) }
  }
  const n = value.trim() === '' ? null : Math.max(0, Math.floor(Number(value)))
  return (
    <form className="limit-editor" onSubmit={e => { e.preventDefault(); if (n !== null && !Number.isNaN(n)) void save(n) }}>
      <input type="number" min={0} step={100} value={value} onChange={e => setValue(e.target.value)} placeholder="Default"
        aria-label={`Page limit for ${user.username}`} style={{ width: 96 }} />
      <button className="sm" disabled={busy || n === null || Number.isNaN(n)}>Set</button>
      {user.custom_page_limit && <button type="button" className="ghost sm" disabled={busy} onClick={() => save(null)}>Reset</button>}
      {busy && <Spinner />}
    </form>
  )
}

export default function AdminUsers() {
  const { session } = useAuth()
  const toast = useToast()
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<AdminUser[] | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    const t = window.setTimeout(() => admin.users(q).then(setRows).catch(e => setErr(e.message)), 250)
    return () => window.clearTimeout(t)
  }, [q])

  const setRole = async (u: AdminUser, role: 'student' | 'admin') => {
    if (u.id === session!.user_id && role === 'student' && !confirm('Remove your own admin access? You will lose access to this console.')) return
    try {
      const next = await admin.updateUser(u.id, { role })
      if (u.id === session!.user_id && role === 'student') { window.location.assign('/'); return }  // reload picks up the new role
      setRows(r => r!.map(x => x.id === u.id ? next : x))
      toast('ok', `${u.username} is now ${role === 'admin' ? 'an admin' : 'a student'}`)
    } catch (e) { toast('err', (e as Error).message) }
  }

  return (
    <>
      <PageHeader title="Users & roles" sub="Grant or revoke admin access. Admins can use this console, proctor exams and manage token budgets." />
      <div className="table-search" style={{ marginBottom: 16 }}><Icon name="search" size={16} />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search username or email" aria-label="Search users" /></div>
      {err && <ErrorBox>{err}</ErrorBox>}
      {!rows ? <Skeleton lines={5} /> : (
        <div className="card table-card"><table className="table">
          <thead><tr><th>User</th><th>Joined</th><th className="r">Exams</th><th className="r">Tokens (month)</th><th>Storage (pages)</th><th>Role</th></tr></thead>
          <tbody>{rows.map(u => (
            <tr key={u.id}>
              <td><b>{u.username}</b>{u.id === session!.user_id && <span className="badge" style={{ marginLeft: 6 }}>You</span>}
                {u.email && <div className="muted">{u.email}</div>}</td>
              <td className="muted">{utc(u.created_at).toLocaleDateString()}</td>
              <td className="r num">{u.exams_taken}</td>
              <td className="r num">{compact(u.tokens_used)}</td>
              <td><div className="num" style={{ marginBottom: 4 }}>{u.pages_used} / {u.page_limit || '∞'}{!u.custom_page_limit && <span className="muted"> default</span>}</div>
                <PageLimit user={u} onSaved={next => setRows(r => r!.map(x => x.id === next.id ? next : x))} /></td>
              <td><select value={u.role} onChange={e => setRole(u, e.target.value as 'student' | 'admin')} aria-label={`Role for ${u.username}`}>
                <option value="student">Student</option><option value="admin">Admin</option></select></td>
            </tr>))}
            {!rows.length && <tr><td colSpan={6} className="muted">No users match.</td></tr>}</tbody>
        </table></div>)}
    </>
  )
}
