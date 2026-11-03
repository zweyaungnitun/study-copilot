import { motion } from 'motion/react'
import { api, type LeaderEntry } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Empty, ErrorBox, Icon, PageHeader, Skeleton } from '../ui'

const PODIUM_H: Record<number, number> = { 1: 132, 2: 96, 3: 72 }

/** Top three on a podium: second, first, third, with the bars rising in. */
function Podium({ top, me }: { top: LeaderEntry[]; me: string }) {
  const order = [top[1], top[0], top[2]].filter(Boolean)
  return (
    <div className="podium" aria-label="Top three">
      {order.map((r, i) => (
        <motion.div key={r.user_id} className={`podium-col p${r.rank} ${r.user_id === me ? 'me' : ''}`}
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.1, type: 'spring', stiffness: 200, damping: 22 }}>
          <span className="podium-avatar">{r.username[0]?.toUpperCase()}{r.rank === 1 && <Icon name="trophy" size={14} />}</span>
          <b>{r.username}{r.user_id === me && <span className="badge">You</span>}</b>
          <span className="muted num">{r.consistency_score} pts · {r.streak_days}d streak</span>
          <motion.div className="podium-bar" initial={{ height: 0 }} animate={{ height: PODIUM_H[r.rank] }}
            transition={{ delay: 0.35 + i * 0.12, type: 'spring', stiffness: 120, damping: 18 }}><span className="num">{r.rank}</span></motion.div>
        </motion.div>))}
    </div>
  )
}

export default function Leaderboard() {
  const { session } = useAuth()
  const { data, error, loading } = useLoad(() => api.leaderboard(), [])
  const head = <PageHeader title="Leaderboard" sub="Ranked by study consistency, not raw hours." />
  if (loading) return <>{head}<Skeleton lines={5} /></>
  if (error || !data) return <>{head}<ErrorBox>{error}</ErrorBox></>
  if (!data.rankings.length) return <>{head}<Empty icon="trophy" title="No rankings yet">Complete a study session to appear here.</Empty></>
  const max = Math.max(1, ...data.rankings.map(r => r.consistency_score))
  return (
    <>
      {head}
      <div className="card"><Podium top={data.rankings.slice(0, 3)} me={session!.user_id} /></div>
      <div className="card">
        <div className="card-head"><h2>All learners</h2><span className="muted">{data.total_participants} studying</span></div>
        <ol className="ranks">{data.rankings.map((r, i) => {
          const me = r.user_id === session!.user_id
          return (
            <motion.li key={r.user_id} className={me ? 'me' : ''} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i }}>
              <span className="rank-n num">{r.rank}</span>
              <span className="rank-who"><b>{r.username}</b>{me && <span className="badge">You</span>}<span className="muted">{r.sessions_completed} sessions</span></span>
              <span className="rank-bar" aria-hidden="true"><motion.i initial={{ width: 0 }} animate={{ width: `${(r.consistency_score / max) * 100}%` }}
                transition={{ delay: 0.2 + 0.05 * i, duration: 0.8, ease: [0.16, 1, 0.3, 1] }} /></span>
              <span className="rank-streak"><Icon name="flame" size={13} />{r.streak_days}d</span>
              <b className="num rank-score" title="Consistency score">{r.consistency_score}</b>
            </motion.li>)
        })}</ol>
      </div>
    </>
  )
}
