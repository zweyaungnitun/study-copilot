import { useState, type FormEvent } from 'react'
import { motion } from 'motion/react'
import { useAuth } from '../auth'
import { Brand, ErrorBox, Icon, Spinner, type IconName } from '../ui'

const perks: [IconName, string][] = [
  ['map', 'A personalised roadmap built around your goal and deadline'],
  ['calendar', 'A day-by-day schedule built from your own textbooks and notes'],
  ['chat', 'An AI tutor that guides you with hints, not just answers'],
]

const rise = (delay: number) => ({ initial: { opacity: 0, y: 28, scale: 0.96 }, animate: { opacity: 1, y: 0, scale: 1 },
  transition: { delay, type: 'spring' as const, stiffness: 140, damping: 18 } })

/** A glimpse of the product: a day's plan, a cited tutor answer and progress, floating gently. */
function Preview() {
  return (
    <div className="auth-preview" aria-hidden="true">
      <motion.div className="pv pv-plan" {...rise(0.25)}>
        <b>Today’s plan</b>
        <span className="pv-row done"><i />Review · Paxos quorums<em>15m</em></span>
        <span className="pv-row now"><i />Learn · Raft leader election<em>40m</em></span>
        <span className="pv-row"><i />Past paper 2023 · Q3<em>20m</em></span>
      </motion.div>
      <motion.div className="pv pv-tutor" {...rise(0.45)}>
        <span className="pv-orb"><Icon name="spark" size={14} /></span>
        <p>Any two majorities share at least one node, so a chosen value can’t be lost <sup>1</sup></p>
        <span className="pv-cite"><b>1</b>Textbook · p.118</span>
      </motion.div>
      <motion.div className="pv pv-ring" {...rise(0.65)}>
        <svg width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="26" fill="none" strokeWidth="7" className="pv-ring-bg" />
          <motion.circle cx="32" cy="32" r="26" fill="none" strokeWidth="7" strokeLinecap="round" className="pv-ring-fg" transform="rotate(-90 32 32)"
            initial={{ pathLength: 0 }} animate={{ pathLength: 0.68 }} transition={{ delay: 0.9, duration: 1.4, ease: [0.16, 1, 0.3, 1] }} /></svg>
        <span><b>68%</b>Mastery</span>
      </motion.div>
    </div>
  )
}

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
        <div className="auth-story">
          <motion.h2 initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}>
            Study smarter.<br /><span>Remember longer.</span></motion.h2>
          <Preview />
          <ul>{perks.map(([ic, t], i) => (
            <motion.li key={t} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.9 + i * 0.08 }}>
              <Icon name={ic} size={18} />{t}</motion.li>))}</ul>
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
