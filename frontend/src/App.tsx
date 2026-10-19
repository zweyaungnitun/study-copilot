import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth'
import { Brand, Icon, applyTheme, initialTheme, type IconName, type Theme } from './ui'
import Login from './pages/Login'
import Onboarding from './pages/Onboarding'
import Dashboard from './pages/Dashboard'
import RoadmapPage from './pages/Roadmap'
import ChapterPage from './pages/Chapter'
import Flashcards from './pages/Flashcards'
import Tutor from './pages/Tutor'
import BrainMapPage from './pages/BrainMap'
import Library from './pages/Library'
import Mistakes from './pages/Mistakes'
import Leaderboard from './pages/Leaderboard'

const learn: [string, string, IconName][] = [
  ['/', 'Home', 'home'], ['/roadmap', 'Roadmap', 'map'], ['/flashcards', 'Flashcards', 'cards'], ['/tutor', 'AI Tutor', 'chat'],
]
const insights: [string, string, IconName][] = [
  ['/brain-map', 'Brain Map', 'brain'], ['/library', 'Library', 'book'], ['/mistakes', 'Mistakes', 'alert'], ['/leaderboard', 'Leaderboard', 'trophy'],
]
const mobilePrimary = [...learn.slice(0, 4)]

const Links = ({ items, onClick }: { items: typeof learn; onClick?: () => void }) => (
  <>{items.map(([to, label, ic]) => (
    <NavLink key={to} to={to} end={to === '/'} onClick={onClick}><Icon name={ic} />{label}</NavLink>))}</>
)

export default function App() {
  const { session, logout } = useAuth()
  const [theme, setTheme] = useState<Theme>(initialTheme())
  const [sheet, setSheet] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => { setSheet(false); window.scrollTo(0, 0) }, [pathname])

  if (!session) return <Routes><Route path="*" element={<Login />} /></Routes>

  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  const toggle = () => { const t: Theme = dark ? 'light' : 'dark'; setTheme(t); applyTheme(t) }
  const themeBtn = <button className="nav-btn" onClick={toggle}><Icon name={dark ? 'sun' : 'moon'} />{dark ? 'Light mode' : 'Dark mode'}</button>

  return (
    <>
      <div className="topbar mobile-only"><Brand /><span className="avatar">{session.username[0]?.toUpperCase()}</span></div>
      <nav className="nav" aria-label="Main">
        <Brand />
        <div className="nav-label">Learn</div>
        <div className="nav-links desktop-links"><Links items={learn} /></div>
        <div className="nav-label">Insights</div>
        <div className="nav-links desktop-links"><Links items={insights} /></div>
        <div className="nav-links mobile-only"><Links items={mobilePrimary} />
          <button className="nav-btn" onClick={() => setSheet(true)} aria-label="More"><Icon name="more" />More</button></div>
        <div className="nav-foot">
          {themeBtn}
          <div className="user">
            <span className="avatar">{session.username[0]?.toUpperCase()}</span>
            <div className="user-details">
              <span className="who">{session.username}</span>
              <span className="status-label">Active Learner 🔥</span>
            </div>
          </div>
          <button className="nav-btn" onClick={logout}><Icon name="logout" />Log out</button>
        </div>
      </nav>
      {sheet && <>
        <div className="sheet-backdrop" onClick={() => setSheet(false)} />
        <div className="sheet" role="dialog" aria-label="More">
          <div className="grab" />
          <Links items={insights} onClick={() => setSheet(false)} />
          {themeBtn}
          <button className="nav-btn" onClick={logout}><Icon name="logout" />Log out ({session.username})</button>
        </div></>}
      <main key={pathname}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/roadmap" element={<RoadmapPage />} />
          <Route path="/chapters/:id" element={<ChapterPage />} />
          <Route path="/flashcards" element={<Flashcards />} />
          <Route path="/tutor" element={<Tutor />} />
          <Route path="/brain-map" element={<BrainMapPage />} />
          <Route path="/library" element={<Library />} />
          <Route path="/mistakes" element={<Mistakes />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </>
  )
}
