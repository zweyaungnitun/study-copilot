import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth'
import { Brand, ErrorBox, Icon, Spinner, type IconName } from '../ui'

const perks: [IconName, string][] = [
  ['map', 'A personalised roadmap built around your goal and deadline'],
  ['cards', 'Spaced-repetition flashcards that adapt to what you forget'],
  ['chat', 'An AI tutor that guides you with hints, not just answers'],
]

export default function Login() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setU] = useState('')
  const [password, setP] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const isLogin = mode === 'login'

  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(''); setBusy(true)
    try { await (isLogin ? login : register)(username, password) }
    catch (x) { setErr((x as Error).message) }
    finally { setBusy(false) }
  }
  return (
    <div className="auth">
      <aside className="auth-hero">
        <Brand size="lg" />
        <div>
          <h2>Study smarter. Remember longer.</h2>
          <ul>{perks.map(([ic, t]) => <li key={t}><Icon name={ic} size={20} />{t}</li>)}</ul>
        </div>
        <span style={{ opacity: .7, fontSize: 13 }}>© StudyPilot</span>
      </aside>
      <section className="auth-form">
        <div className="auth-card">
          <Brand />
          <h1>{isLogin ? 'Welcome back' : 'Create your account'}</h1>
          <p className="page-sub">{isLogin ? 'Log in to continue your learning streak.' : 'Start building your study plan in minutes.'}</p>
          <form onSubmit={submit}>
            <label htmlFor="u">Username</label>
            <input id="u" value={username} onChange={e => setU(e.target.value)} minLength={3} autoComplete="username" required autoFocus />
            <label htmlFor="p">Password <span className="hint">· min 6 characters</span></label>
            <input id="p" type="password" value={password} onChange={e => setP(e.target.value)} minLength={6} autoComplete={isLogin ? 'current-password' : 'new-password'} required />
            {err && <ErrorBox>{err}</ErrorBox>}
            <button className="lg block" style={{ marginTop: 22 }} disabled={busy}>{busy && <Spinner />}{isLogin ? 'Log in' : 'Create account'}</button>
          </form>
          <p className="switch">{isLogin ? 'New here? ' : 'Already have an account? '}
            <button type="button" className="link-btn" onClick={() => { setMode(isLogin ? 'register' : 'login'); setErr('') }}>{isLogin ? 'Create an account' : 'Log in'}</button></p>
        </div>
      </section>
    </div>
  )
}
