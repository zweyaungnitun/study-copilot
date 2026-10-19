import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ReviewResult } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Empty, ErrorBox, PageHeader, ProgressBar, Skeleton } from '../ui'

const labels = ['Blackout', 'Wrong', 'Hard-ish', 'Hard', 'Good', 'Easy']

export default function Flashcards() {
  const { session } = useAuth()
  const { data, error, loading } = useLoad(() => api.dueCards(session!.user_id), [])
  const [i, setI] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const [last, setLast] = useState<ReviewResult | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const card = data?.[i]

  const rate = async (q: number) => {
    if (!card || busy) return
    setBusy(true)
    try { setLast(await api.review(card.id, q)); setI(n => n + 1); setFlipped(false); setErr('') }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,select,textarea')) return
      if (e.code === 'Space') { e.preventDefault(); setFlipped(f => !f) }
      else if (flipped && /^[0-5]$/.test(e.key)) rate(+e.key)
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  })

  if (loading) return <><PageHeader title="Flashcards" /><Skeleton lines={4} /></>
  if (error) return <><PageHeader title="Flashcards" /><ErrorBox>{error}</ErrorBox></>
  if (!card) return <><PageHeader title="Flashcards" />
    <Empty icon="cards" title="You're all caught up" action={<Link to="/roadmap"><button className="ghost">Open a chapter</button></Link>}>
      {last ? `Last review: next one due in ${last.interval} day(s). ` : ''}No cards are due. Generate more from any chapter page.</Empty></>

  return (
    <>
      <PageHeader title="Flashcards" sub="Rate honestly — spaced repetition does the rest." />
      <div className="deck-wrap">
        <div className="deck-meta"><span className="muted num">Card {i + 1} of {data!.length}</span><span className="muted"><kbd>Space</kbd> flip · <kbd>0–5</kbd> rate</span></div>
        <ProgressBar value={(i / data!.length) * 100} />
        <button className={`flip ${flipped ? 'back' : ''}`} style={{ marginTop: 16 }} onClick={() => setFlipped(f => !f)} aria-label="Flip card">
          <div key={String(flipped) + card.id}>
            <div className="side">{flipped ? 'Answer' : 'Question'}</div>
            <div className="text">{flipped ? card.back : card.front}</div>
            <div className="src">{flipped ? card.source_citation || card.source : 'Tap to reveal the answer'}</div>
          </div>
        </button>
        {flipped
          ? <div className="rate">{labels.map((l, q) => <button key={q} disabled={busy} className={q < 3 ? 'bad' : 'good'} onClick={() => rate(q)}><b>{q}</b>{l}</button>)}</div>
          : <p className="muted" style={{ textAlign: 'center' }}>Think of the answer first, then flip.</p>}
        {last && <p className="muted" style={{ marginTop: 14, textAlign: 'center' }}>Previous card: next review in {last.interval} day(s) · ease {last.ease.toFixed(2)}</p>}
        {err && <ErrorBox>{err}</ErrorBox>}
      </div>
    </>
  )
}
