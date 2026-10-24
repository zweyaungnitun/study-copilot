import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from '../auth'
import { Brand, Icon, applyTheme, initialTheme, type IconName, type Theme } from '../ui'
import AdminOverview from './AdminOverview'
import AdminProctoring from './AdminProctoring'
import AdminMaterials from './AdminMaterials'
import AdminTokens from './AdminTokens'
import AdminUsers from './AdminUsers'

type NavItem = [to: string, label: string, icon: IconName]
const items: NavItem[] = [
  ['/admin', 'Dashboard', 'gauge'], ['/admin/proctoring', 'Proctoring', 'shield'],
  ['/admin/tokens', 'Token management', 'coins'], ['/admin/materials', 'Materials', 'book'], ['/admin/users', 'Users & roles', 'users'],
]

const Links = () => <>{items.map(([to, label, ic]) => (
  <NavLink key={to} to={to} end={to === '/admin'} title={label}>
    <span className="nav-icon"><Icon name={ic} /></span><span className="nav-text">{label}</span></NavLink>))}</>

/** The admin site: its own shell and navigation, mounted at /admin for admin accounts. */
export default function AdminApp() {
  const { session, logout } = useAuth()
  const { pathname } = useLocation()
  const [theme, setTheme] = useState<Theme>(initialTheme())
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  const toggleTheme = () => { const t: Theme = dark ? 'light' : 'dark'; setTheme(t); applyTheme(t) }
  const page = items.find(([to]) => to === pathname)?.[1] ?? 'Dashboard'

  return (
    <div className="shell admin">
      <div className="aurora" aria-hidden="true"><i /><i /><i /></div>
      <nav className="nav" aria-label="Admin">
        <div className="nav-top"><Link to="/admin" className="brand-link" aria-label="Admin home"><Brand /></Link>
          <span className="badge admin-badge nav-text">Admin</span></div>
        <div className="nav-scroll">
          <div className="nav-label">Console</div>
          <div className="nav-links"><Links /></div>
          <div className="nav-label">Switch</div>
          <div className="nav-links"><Link to="/" title="Back to the learner app"><span className="nav-icon"><Icon name="back" /></span><span className="nav-text">Learner app</span></Link></div>
        </div>
        <div className="nav-foot"><div className="user">
          <span className="avatar">{session!.username[0]?.toUpperCase()}</span>
          <div className="user-details nav-text"><span className="who">{session!.username}</span><span className="status-label">Administrator</span></div>
          <button className="icon-btn nav-text" onClick={logout} title="Log out" aria-label="Log out"><Icon name="logout" size={16} /></button>
        </div></div>
      </nav>

      <div className="frame">
        <header className="topbar">
          <div className="topbar-left">
            <Link to="/admin" className="topbar-brand" aria-label="Admin home"><Brand /></Link>
            <nav className="crumbs" aria-label="Breadcrumb"><span>Admin</span><Icon name="chevron" size={14} /><b>{page}</b></nav>
          </div>
          <div className="topbar-right">
            <button className="icon-btn" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
              <span className={`theme-swap ${dark ? 'is-dark' : ''}`}><Icon name="sun" size={17} /><Icon name="moon" size={17} /></span></button>
          </div>
        </header>
        <main key={pathname}>
          <Routes>
            <Route index element={<AdminOverview />} />
            <Route path="proctoring" element={<AdminProctoring />} />
            <Route path="tokens" element={<AdminTokens />} />
            <Route path="materials" element={<AdminMaterials />} />
            <Route path="users" element={<AdminUsers />} />
            <Route path="*" element={<Navigate to="/admin" />} />
          </Routes>
        </main>
      </div>

      <nav className="dock" aria-label="Admin sections"><Links /></nav>
    </div>
  )
}
