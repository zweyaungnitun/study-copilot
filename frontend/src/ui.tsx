import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

const PATHS = {
  home: 'M3 11l9-8 9 8M5 10v10h14V10',
  map: 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14',
  cards: 'M4 7h13v12H4zM8 7V4h13v12h-4',
  chat: 'M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z',
  brain: 'M12 3a4 4 0 00-4 4 4 4 0 00-3 4 4 4 0 002 3.5A4 4 0 0012 19a4 4 0 005-4.5 4 4 0 002-3.5 4 4 0 00-3-4 4 4 0 00-4-4zM12 3v16',
  book: 'M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2zM4 19a2 2 0 012-2h13',
  alert: 'M12 3l10 18H2zM12 10v5M12 18v.5',
  trophy: 'M8 4h8v6a4 4 0 01-8 0zM8 6H4v1a4 4 0 004 4M16 6h4v1a4 4 0 01-4 4M12 14v4M8 21h8',
  spark: 'M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z',
  flame: 'M12 2s5 4.5 5 10a5 5 0 01-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-6 1-9z',
  clock: 'M12 7v5l3 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  star: 'M12 3l2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.8 6.2 20.9l1.1-6.5L2.6 9.8l6.5-.9z',
  x: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  sun: 'M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6L4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M16 12a4 4 0 11-8 0 4 4 0 018 0z',
  moon: 'M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z',
  logout: 'M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3M10 8l-4 4 4 4M6 12h11',
  send: 'M5 12l14-7-5 14-2-6z',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  file: 'M7 3h7l5 5v13H7zM14 3v5h5',
  lock: 'M6 11h12v9H6zM8 11V8a4 4 0 018 0v3',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  back: 'M19 12H5M11 6l-6 6 6 6',
  target: 'M12 12m-1 0a1 1 0 102 0 1 1 0 10-2 0M12 12m-5 0a5 5 0 1010 0 5 5 0 10-10 0M12 12m-9 0a9 9 0 1018 0 9 9 0 10-18 0',
  refresh: 'M20 11a8 8 0 00-14.9-3M4 4v4h4M4 13a8 8 0 0014.9 3M20 20v-4h-4',
} as const
export type IconName = keyof typeof PATHS

export const Icon = ({ name, size = 18 }: { name: IconName; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={PATHS[name]} /></svg>
)

export const Brand = ({ size = 'md' }: { size?: 'md' | 'lg' }) => (
  <div className={`brand ${size}`}>
    <span className="brand-mark"><Icon name="spark" size={size === 'lg' ? 22 : 18} /></span>
    <span className="brand-name">StudyPilot<span className="brand-badge">AI</span></span>
  </div>
)

export function PageHeader({ title, sub, actions, back }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <header className="page-head">
      <div>{back}<h1>{title}</h1>{sub && <p className="page-sub">{sub}</p>}</div>
      {actions && <div className="row actions">{actions}</div>}
    </header>
  )
}

export function Empty({ icon, title, children, action }: { icon: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card empty">
      <span className="empty-icon"><Icon name={icon} size={24} /></span>
      <h2>{title}</h2>
      {children && <p className="muted">{children}</p>}
      {action}
    </div>
  )
}

export const Skeleton = ({ lines = 3 }: { lines?: number }) => (
  <div className="card" aria-busy="true" aria-label="Loading">
    {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton" style={{ width: `${90 - i * 18}%`, marginBottom: 12 }} />)}
  </div>
)

export const ErrorBox = ({ children }: { children: ReactNode }) => <div className="alert err-box" role="alert"><Icon name="alert" size={16} />{children}</div>

export const Spinner = () => <span className="spinner" role="status" aria-label="Loading" />

export const Segmented = <T extends string | number>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: [T, string][]; label: string
}) => (
  <div className="seg" role="radiogroup" aria-label={label}>
    {options.map(([v, l]) => (
      <button type="button" key={String(v)} role="radio" aria-checked={v === value} className={v === value ? 'on' : ''} onClick={() => onChange(v)}>{l}</button>
    ))}
  </div>
)

export const ProgressBar = ({ value, tone = 'accent' }: { value: number; tone?: 'accent' | 'green' }) => (
  <div className="bar" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
    <i className={tone} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
  </div>
)

/** Minimal markdown: headings, bullets, numbered lists, **bold**, `code`, paragraphs. */
export function Markdown({ text }: { text: string }) {
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
    p.startsWith('**') ? <strong key={i}>{p.slice(2, -2)}</strong> : p.startsWith('`') ? <code key={i}>{p.slice(1, -1)}</code> : p)
  const out: ReactNode[] = []
  let list: { ordered: boolean; items: ReactNode[] } | null = null
  const flush = () => {
    if (!list) return
    const L = list; list = null
    out.push(L.ordered ? <ol key={out.length}>{L.items}</ol> : <ul key={out.length}>{L.items}</ul>)
  }
  text.split('\n').forEach((raw, i) => {
    const l = raw.trimEnd()
    const h = /^(#{1,4})\s+(.*)/.exec(l)
    const li = /^\s*([-*•]|\d+[.)])\s+(.*)/.exec(l)
    if (li) {
      const ordered = /\d/.test(li[1])
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] } }
      list.items.push(<li key={i}>{inline(li[2])}</li>)
    } else {
      flush()
      if (h) out.push(h[1].length <= 2 ? <h3 key={i}>{inline(h[2])}</h3> : <h4 key={i}>{inline(h[2])}</h4>)
      else if (l.trim()) out.push(<p key={i}>{inline(l)}</p>)
    }
  })
  flush()
  return <div className="prose">{out}</div>
}

/* ---------- Toasts ---------- */
interface Toast { id: number; kind: 'ok' | 'err'; text: string }
const ToastCtx = createContext<(kind: Toast['kind'], text: string) => void>(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<Toast[]>([])
  const push = useCallback((kind: Toast['kind'], text: string) => {
    const id = Date.now() + Math.random()
    setList(l => [...l, { id, kind, text }])
    setTimeout(() => setList(l => l.filter(t => t.id !== id)), 4200)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {list.map(t => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <Icon name={t.kind === 'ok' ? 'check' : 'alert'} size={16} />{t.text}
          </div>))}
      </div>
    </ToastCtx.Provider>
  )
}

/* ---------- Theme ---------- */
export type Theme = 'system' | 'light' | 'dark'
export function applyTheme(t: Theme) {
  if (t === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', t)
  try { localStorage.setItem('sp_theme', t) } catch { /* ignore */ }
}
export function initialTheme(): Theme {
  try { const t = localStorage.getItem('sp_theme'); if (t === 'light' || t === 'dark') return t } catch { /* ignore */ }
  return 'system'
}
