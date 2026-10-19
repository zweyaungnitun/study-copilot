import { api } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Empty, ErrorBox, Icon, PageHeader, Skeleton } from '../ui'

export default function Leaderboard() {
  const { session } = useAuth()
  const { data, error, loading } = useLoad(() => api.leaderboard(), [])
  const head = <PageHeader title="Leaderboard" sub="Ranked by study consistency, not raw hours." />
  if (loading) return <>{head}<Skeleton lines={5} /></>
  if (error || !data) return <>{head}<ErrorBox>{error}</ErrorBox></>
  if (!data.rankings.length) return <>{head}<Empty icon="trophy" title="No rankings yet">Complete a study session to appear here.</Empty></>
  return (
    <>
      {head}
      <div className="card"><div className="list">
        {data.rankings.map(r => {
          const me = r.user_id === session!.user_id
          return (
            <div className={`item stack ${me ? 'me-row' : ''}`} key={r.user_id} style={me ? { paddingInline: 8 } : undefined}>
              <div className="main"><span className={`rank ${r.rank <= 3 ? `r${r.rank}` : ''}`}>{r.rank}</span>
                <div><div className="title">{r.username}{me && <span className="badge" style={{ marginLeft: 8 }}>You</span>}</div>
                  <div className="muted">{r.sessions_completed} sessions</div></div></div>
              <div className="row">
                <span className="badge yellow"><Icon name="flame" size={12} />{r.streak_days} day streak</span>
                <b className="num" title="Consistency score">{r.consistency_score}</b></div>
            </div>)
        })}
      </div></div>
    </>
  )
}
