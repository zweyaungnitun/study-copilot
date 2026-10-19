import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useLoad } from '../hooks'
import { ErrorBox, Icon, Markdown, PageHeader, Segmented, Skeleton, Spinner, useToast } from '../ui'

const tiers: ['simple_content' | 'detailed_content' | 'exam_content' | 'cheat_sheet', string][] =
  [['simple_content', 'Simple'], ['detailed_content', 'Detailed'], ['exam_content', 'Exam'], ['cheat_sheet', 'Cheat sheet']]

export default function ChapterPage() {
  const { id } = useParams()
  const toast = useToast()
  const { data, error, loading } = useLoad(() => api.notes(id!), [id])
  const [tier, setTier] = useState<(typeof tiers)[number][0]>('simple_content')
  const [busy, setBusy] = useState(false)

  const gen = async () => {
    setBusy(true)
    try { const c = await api.genCards(id!); toast('ok', `Created ${c.length} flashcards`) }
    catch (e) { toast('err', (e as Error).message) } finally { setBusy(false) }
  }
  const back = <Link to="/roadmap" className="back"><Icon name="back" size={15} />Roadmap</Link>
  if (loading) return <><PageHeader title="Chapter notes" back={back} sub="Generating your notes…" /><Skeleton lines={5} /></>
  if (error || !data) return <><PageHeader title="Chapter notes" back={back} /><ErrorBox>{error}</ErrorBox></>
  return (
    <>
      <PageHeader title="Chapter notes" back={back} sub="Study at the depth you need."
        actions={<>
          <Link to={`/tutor?chapter=${id}`}><button className="ghost"><Icon name="chat" size={16} />Ask the tutor</button></Link>
          <button onClick={gen} disabled={busy}>{busy ? <Spinner /> : <Icon name="cards" size={16} />}Generate flashcards</button></>} />
      <div style={{ marginBottom: 16 }}><Segmented label="Detail level" value={tier} onChange={setTier} options={tiers} /></div>
      <div className="card" style={{ padding: 28 }}>{data[tier] ? <Markdown text={data[tier]!} /> : <p className="muted">Nothing here yet.</p>}</div>
    </>
  )
}
