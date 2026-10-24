import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api, type Roadmap } from './api'
import { useAuth } from './auth'
import { Brand, Icon, ProgressRing, applyTheme, initialTheme, type IconName, type Theme } from './ui'
import { CommandPalette, useCommandHotkey, type Command } from './CommandPalette'
import Login from './pages/Login'
import Onboarding from './pages/Onboarding'
import Dashboard from './pages/Dashboard'
import RoadmapPage from './pages/Roadmap'
import ChapterPage from './pages/Chapter'
import Tutor from './pages/Tutor'
import BrainMapPage from './pages/BrainMap'
import Library from './pages/Library'
import Mistakes from './pages/Mistakes'
import Leaderboard from './pages/Leaderboard'
import ExamPage from './pages/Exam'
import MaterialsWizard from './pages/MaterialsWizard'
import SchedulePage from './pages/Schedule'
import Usage from './pages/Usage'
import AdminApp from './admin/AdminApp'

type NavItem = [to: string, label: string, icon: IconName]
const learn: NavItem[] = [
  ['/', 'Home', 'home'], ['/schedule', 'Schedule', 'calendar'], ['/roadmap', 'Roadmap', 'map'], ['/tutor', 'AI Tutor', 'chat'],
]
const insights: NavItem[] = [
  ['/brain-map', 'Brain Map', 'brain'], ['/library', 'Library', 'book'], ['/mistakes', 'Mistakes', 'alert'], ['/exam', 'Mock exam', 'exam'],
  ['/leaderboard', 'Leaderboard', 'trophy'], ['/usage', 'AI usage', 'gauge'],
]

/** Breadcrumb for the top bar: [section, page]. */
function crumbFor(path: string): [string, string] {
  if (path.startsWith('/chapters/')) return ['Learn', 'Chapter']
  if (path === '/onboarding') return ['Learn', 'New track']
  if (path === '/tracks/from-materials') return ['Learn', 'Track from materials']
  const hit = learn.find(([to]) => to === path)
  if (hit) return ['Learn', hit[1]]
  const ins = insights.find(([to]) => to === path)
  return ins ? ['Insights', ins[1]] : ['Learn', 'Home']
}

const Links = ({ items, onClick }: { items: NavItem[]; onClick?: () => void }) => (
  <>{items.map(([to, label, ic]) => (
    <NavLink key={to} to={to} end={to === '/'} onClick={onClick} title={label}>
      <span className="nav-icon"><Icon name={ic} /></span><span className="nav-text">{label}</span>
    </NavLink>))}</>
)

const trackPct = (t: Roadmap) => {
  const cs = t.subjects.flatMap(x => x.chapters)
  return cs.length ? cs.reduce((a, c) => a + c.mastery_score, 0) / cs.length : 0
}

export default function App() {
  const { session, isAdmin, logout } = useAuth()
  const navigate = useNavigate()
  const [theme, setTheme] = useState<Theme>(initialTheme())
  const [sheet, setSheet] = useState(false)
  const [palette, setPalette] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const { pathname, search } = useLocation()
  useEffect(() => { setSheet(false); setPalette(false); window.scrollTo(0, 0) }, [pathname])

  useEffect(() => {
    const h = () => setScrolled(window.scrollY > 8)
    h(); window.addEventListener('scroll', h, { passive: true })
    return () => window.removeEventListener('scroll', h)
  }, [])

  // Collapsible sidebar rail; the choice is remembered per browser.
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('sp_nav') === 'collapsed' } catch { return false } })
  useEffect(() => {
    document.documentElement.dataset.nav = collapsed ? 'collapsed' : 'open'
    try { localStorage.setItem('sp_nav', collapsed ? 'collapsed' : 'open') } catch { /* storage unavailable */ }
  }, [collapsed])

  // Tracks in the sidebar, refreshed on navigation so progress rings stay current.
  const [tracks, setTracks] = useState<Roadmap[]>([])
  const uid = session?.user_id
  useEffect(() => {
    if (!uid) { setTracks([]); return }
    let live = true
    api.tracks(uid).then(t => live && setTracks(t)).catch(() => {})
    return () => { live = false }
  }, [uid, pathname])

  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  const toggleTheme = useCallback(() => { const t: Theme = dark ? 'light' : 'dark'; setTheme(t); applyTheme(t) }, [dark])
  const togglePalette = useCallback(() => setPalette(p => !p), [])
  useCommandHotkey(togglePalette)

  const commands = useMemo<Command[]>(() => [
    ...learn.map(([to, label, icon]) => ({ id: to, label, icon, group: 'Learn', run: () => navigate(to) })),
    ...tracks.map(t => ({ id: `t-${t.id}`, label: t.specialization, hint: `${Math.round(trackPct(t))}%`, icon: 'target' as IconName, group: 'Tracks', run: () => navigate(`/roadmap?track=${t.id}`) })),
    ...insights.map(([to, label, icon]) => ({ id: to, label, icon, group: 'Insights', run: () => navigate(to) })),
    ...(isAdmin ? [{ id: 'admin', label: 'Open admin console', icon: 'shield' as IconName, group: 'Actions', run: () => navigate('/admin') }] : []),
    { id: 'new', label: 'Start a new track', icon: 'plus', group: 'Actions', run: () => navigate('/onboarding') },
    { id: 'theme', label: dark ? 'Switch to light mode' : 'Switch to dark mode', icon: dark ? 'sun' : 'moon', group: 'Actions', run: toggleTheme },
    { id: 'nav', label: collapsed ? 'Expand sidebar' : 'Collapse sidebar', icon: 'sidebar', group: 'Actions', run: () => setCollapsed(c => !c) },
    { id: 'out', label: 'Log out', icon: 'logout', group: 'Actions', run: logout },
  ], [tracks, dark, collapsed, isAdmin, navigate, toggleTheme, logout])

  if (!session) return <Routes><Route path="*" element={<Login />} /></Routes>
  if (pathname === '/admin' || pathname.startsWith('/admin/')) return isAdmin ? <Routes><Route path="/admin/*" element={<AdminApp />} /></Routes> : <Navigate to="/" />

  const [section, page] = crumbFor(pathname)
  const initial = session.username[0]?.toUpperCase()

  return (
    <div className="shell">
      <div className="aurora" aria-hidden="true"><i /><i /><i /></div>

      <nav className="nav" aria-label="Main">
        <div className="nav-top">
          <Link to="/" className="brand-link" aria-label="StudyPilot home"><Brand /></Link>
          <button className="nav-collapse" onClick={() => setCollapsed(c => !c)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} title={collapsed ? 'Expand' : 'Collapse'}>
            <Icon name="sidebar" size={16} /></button>
        </div>

        <button className="nav-search" onClick={() => setPalette(true)} title="Search (⌘K)">
          <Icon name="search" size={16} /><span className="nav-text">Search…</span><kbd className="nav-text">⌘K</kbd>
        </button>

        <div className="nav-scroll">
          <div className="nav-label">Learn</div>
          <div className="nav-links"><Links items={learn} /></div>
          <div className="nav-label nav-label-row"><span>Tracks</span>
            <Link to="/onboarding" className="nav-add" title="New track" aria-label="New track"><Icon name="plus" size={14} /></Link></div>
          <div className="nav-links">{tracks.length === 0
            ? <Link to="/onboarding" className="track-link ghost"><span className="nav-icon"><Icon name="plus" size={16} /></span><span className="nav-text">Create your first track</span></Link>
            : tracks.map(t => {
              const pct = trackPct(t)
              const on = pathname === '/roadmap' && new URLSearchParams(search).get('track') === t.id
              return <Link key={t.id} to={`/roadmap?track=${t.id}`} className={`track-link ${on ? 'active' : ''}`} title={`${t.specialization} · ${Math.round(pct)}%`}>
                <span className="nav-icon"><ProgressRing value={pct} size={20} stroke={3} label={`${Math.round(pct)} percent`} /></span>
                <span className="nav-text">{t.specialization}</span><span className="nav-text nav-pct num">{Math.round(pct)}%</span></Link>
            })}</div>
          <div className="nav-label">Insights</div>
          <div className="nav-links"><Links items={insights} /></div>
          {isAdmin && <><div className="nav-label">Admin</div>
            <div className="nav-links"><Links items={[['/admin', 'Admin console', 'shield']]} /></div></>}
        </div>

        <div className="nav-foot">
          <div className="user">
            <span className="avatar">{initial}</span>
            <div className="user-details nav-text">
              <span className="who">{session.username}</span>
              <span className="status-label">{isAdmin ? 'Administrator' : 'Active learner'}</span>
            </div>
            <button className="icon-btn nav-text" onClick={logout} title="Log out" aria-label="Log out"><Icon name="logout" size={16} /></button>
          </div>
        </div>
      </nav>

      <div className="frame">
        <header className={`topbar ${scrolled ? 'scrolled' : ''}`}>
          <div className="topbar-left">
            <Link to="/" className="topbar-brand" aria-label="StudyPilot home"><Brand /></Link>
            <nav className="crumbs" aria-label="Breadcrumb"><span>{section}</span><Icon name="chevron" size={14} /><b>{page}</b></nav>
          </div>
          <div className="topbar-right">
            <button className="search-pill" onClick={() => setPalette(true)} aria-label="Open command palette">
              <Icon name="search" size={16} /><span>Search or jump to…</span><kbd>⌘K</kbd>
            </button>
            <button className="icon-btn" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
              <span className={`theme-swap ${dark ? 'is-dark' : ''}`}><Icon name="sun" size={17} /><Icon name="moon" size={17} /></span>
            </button>
            <span className="avatar topbar-avatar" title={session.username}>{initial}</span>
          </div>
        </header>

        <main key={pathname}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/onboarding" element={<Onboarding />} />
            <Route path="/roadmap" element={<RoadmapPage />} />
            <Route path="/chapters/:id" element={<ChapterPage />} />
            <Route path="/tutor" element={<Tutor />} />
            <Route path="/brain-map" element={<BrainMapPage />} />
            <Route path="/library" element={<Library />} />
            <Route path="/mistakes" element={<Mistakes />} />
            <Route path="/leaderboard" element={<Leaderboard />} />
            <Route path="/exam" element={<ExamPage />} />
            <Route path="/schedule" element={<SchedulePage />} />
            <Route path="/tracks/from-materials" element={<MaterialsWizard />} />
            <Route path="/usage" element={<Usage />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>

      <nav className="dock" aria-label="Primary">
        <Links items={learn} />
        <button className={`dock-more ${sheet ? 'active' : ''}`} onClick={() => setSheet(true)} aria-label="More">
          <span className="nav-icon"><Icon name="more" /></span><span className="nav-text">More</span></button>
      </nav>

      {sheet && <>
        <div className="sheet-backdrop" onClick={() => setSheet(false)} />
        <div className="sheet" role="dialog" aria-label="More">
          <div className="grab" />
          <div className="sheet-grid"><Links items={insights} onClick={() => setSheet(false)} /></div>
          {tracks.length > 0 && <>
            <div className="nav-label">Tracks</div>
            {tracks.map(t => <Link key={t.id} to={`/roadmap?track=${t.id}`} className="sheet-row" onClick={() => setSheet(false)}>
              <ProgressRing value={trackPct(t)} size={22} stroke={3} /><span>{t.specialization}</span><span className="muted num">{Math.round(trackPct(t))}%</span></Link>)}
          </>}
          <div className="sheet-actions">
            <button className="sheet-row" onClick={() => { setSheet(false); setPalette(true) }}><Icon name="search" />Search</button>
            {isAdmin && <Link to="/admin" className="sheet-row" onClick={() => setSheet(false)}><Icon name="shield" />Admin console</Link>}
            <button className="sheet-row" onClick={toggleTheme}><Icon name={dark ? 'sun' : 'moon'} />{dark ? 'Light mode' : 'Dark mode'}</button>
            <button className="sheet-row" onClick={logout}><Icon name="logout" />Log out ({session.username})</button>
          </div>
        </div></>}

      <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} />
    </div>
  )
}
