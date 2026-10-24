import { utc, type Attempt, type Risk } from '../api'
import { Icon, type IconName } from '../ui'

const RISK: Record<Risk, [string, string]> = { low: ['green', 'Low risk'], medium: ['yellow', 'Medium risk'], high: ['red', 'High risk'] }

/** Risk is a status: color plus icon plus words, never color alone. */
export const RiskBadge = ({ risk, score }: { risk: Risk; score: number }) => (
  <span className={`badge ${RISK[risk][0]}`} title={`Integrity ${score}/100`}>
    <Icon name={risk === 'low' ? 'check' : 'alert'} size={12} />{RISK[risk][1]} · {score}</span>
)

export function StatusBadge({ a }: { a: Attempt }) {
  if (a.status === 'in_progress') return a.live
    ? <span className="badge green"><span className="live-dot" />Live</span>
    : <span className="badge gray" title={a.overdue ? 'Time limit passed without a submission' : 'No heartbeat recently'}>{a.overdue ? 'Abandoned' : 'Idle'}</span>
  if (a.status === 'terminated') return <span className="badge red"><Icon name="stop" size={12} />Terminated</span>
  return <span className="badge gray"><Icon name="check" size={12} />Submitted</span>
}

export const ReviewBadge = ({ a }: { a: Attempt }) => a.review_verdict
  ? <span className={`badge ${a.review_verdict === 'cleared' ? 'green' : 'red'}`}>{a.review_verdict === 'cleared' ? 'Cleared' : 'Violation confirmed'}</span>
  : a.flag_count > 0 && a.status !== 'in_progress' ? <span className="badge yellow">Needs review</span> : null

export const ago = (iso?: string | null) => {
  if (!iso) return '—'
  const s = Math.round((Date.now() - utc(iso).getTime()) / 1000)
  if (s < 60) return `${Math.max(0, s)}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return utc(iso).toLocaleDateString()
}

export const EVENT_LABELS: Record<string, [string, IconName]> = {
  exam_started: ['Exam started', 'exam'], tab_hidden: ['Switched away from the tab', 'eye'],
  window_blur: ['Focused another window', 'eye'], fullscreen_exit: ['Left fullscreen', 'sidebar'],
  fullscreen_enter: ['Entered fullscreen', 'sidebar'], copy: ['Tried to copy', 'copy'], paste: ['Tried to paste', 'copy'],
  context_menu: ['Opened the context menu', 'more'], print_screen: ['Pressed Print Screen', 'alert'],
  multiple_screens: ['Multiple displays detected', 'alert'], admin_warning: ['Proctor warning sent', 'chat'],
  terminated: ['Exam terminated', 'stop'],
}

export function Stat({ icon, tone, value, label, hint }: { icon: IconName; tone?: string; value: React.ReactNode; label: string; hint?: React.ReactNode }) {
  return (
    <div className="card">
      <span className={`stat-icon ${tone ?? ''}`}><Icon name={icon} /></span>
      <div><div className="stat num">{value}</div><div className="stat-label">{label}</div>{hint && <div className="stat-hint">{hint}</div>}</div>
    </div>
  )
}
