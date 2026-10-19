import { api } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Empty, ErrorBox, Icon, PageHeader, Skeleton, useToast } from '../ui'

export default function Mistakes() {
  const { session } = useAuth()
  const toast = useToast()
  const { data, error, loading, setData } = useLoad(() => api.mistakes(session!.user_id), [])
  const head = <PageHeader title="Mistake notebook" sub={data?.length ? `${data.length} to review — fix the pattern, not just the answer.` : 'Learn from what tripped you up.'} />
  if (loading) return <>{head}<Skeleton lines={4} /></>
  if (error) return <>{head}<ErrorBox>{error}</ErrorBox></>
  const resolve = async (id: string) => {
    try { await api.resolveMistake(id); setData(data!.filter(m => m.id !== id)); toast('ok', 'Marked as resolved') }
    catch (e) { toast('err', (e as Error).message) }
  }
  return (
    <>
      {head}
      {!data?.length && <Empty icon="check" title="No open mistakes">Nice work. New mistakes from quizzes will show up here.</Empty>}
      {data?.map(m => (
        <div className="card" key={m.id}>
          <div className="card-head"><h2 style={{ fontSize: 17 }}>{m.question}</h2>{m.misconception_tag && <span className="badge yellow">{m.misconception_tag}</span>}</div>
          <div className="qa"><div className="wrong"><small>Your answer</small>{m.student_answer}</div><div className="right"><small>Correct answer</small>{m.correct_answer}</div></div>
          <p className="muted" style={{ marginBottom: 14 }}>{m.explanation}</p>
          <button className="ghost sm" onClick={() => resolve(m.id)}><Icon name="check" size={14} />Mark resolved</button>
        </div>))}
    </>
  )
}
