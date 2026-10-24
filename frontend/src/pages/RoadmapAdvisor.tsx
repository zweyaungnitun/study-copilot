import { useEffect, useRef, useState } from 'react'
import { api, type ChatMsg, type Proposal, type Roadmap } from '../api'
import ChatHistory from '../ChatHistory'
import { useChats } from '../useChats'
import { Composer, Message, Typing } from '../ChatBits'
import { Icon, useToast } from '../ui'

interface Msg { id?: string; me: boolean; text: string; proposal?: Proposal | null; applied?: boolean }
const toMsg = (m: ChatMsg): Msg => m.role === 'user' ? { me: true, text: m.content }
  : { id: m.id, me: false, text: m.content, proposal: (m.meta.proposal as Proposal | null) ?? null, applied: !!m.meta.applied }

const discussStarters = ['Why is this ordered this way?', 'Can I finish this by my deadline?', 'Make it lighter — fewer chapters', 'Add a chapter on exam practice']
const designStarters = ['I want to learn Spanish for travel', 'Add a statistics track for my data job', 'A track to prepare for the IELTS exam']

type Props =
  | { mode: 'discuss'; userId: string; track: Roadmap; onApplied: (r: Roadmap) => void }
  | { mode: 'design'; userId: string; existing: Roadmap[]; onApplied: (r: Roadmap) => void; onClose: () => void }

/**
 * Chat with the AI about roadmaps.
 *  - discuss: talk about one track; a proposal revises that track (progress is kept).
 *  - design: describe something new; the AI proposes a complete track that is added in parallel.
 */
export default function RoadmapAdvisor(props: Props) {
  const { userId, onApplied } = props
  const design = props.mode === 'design'
  const track = props.mode === 'discuss' ? props.track : null
  const toast = useToast()
  const [open, setOpen] = useState(design)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const chats = useChats<Msg>(userId, design ? 'design' : 'roadmap', track?.id ?? null, toMsg)
  const { msgs, setMsgs } = chats
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [msgs, busy])

  const titles = new Set((track ? [track] : []).flatMap(t => t.subjects.flatMap(s => s.chapters.map(c => c.title))))
  const ask = async (message: string) => {
    message = message.trim(); if (!message || busy) return
    setMsgs(m => [...m, { me: true, text: message }]); setText(''); setBusy(true)
    try {
      const sid = await chats.ensure()
      const r = track ? await api.discussRoadmap(userId, message, sid, track.id) : await api.designTrack(userId, message, sid)
      setMsgs(m => [...m, { id: r.message_id, me: false, text: r.reply, proposal: r.proposal }])
      chats.refresh()
    } catch (e) { setMsgs(m => [...m, { me: false, text: `Sorry — ${(e as Error).message}` }]) }
    finally { setBusy(false) }
  }
  const apply = async (i: number, p: Proposal) => {
    setBusy(true)
    try {
      const r = await api.applyRoadmap(userId, p, track?.id)
      setMsgs(m => m.map((x, j) => j === i ? { ...x, applied: true } : x))
      if (msgs[i].id) api.patchMessage(msgs[i].id!, userId, { applied: true }).catch(() => {})
      toast('ok', track ? 'Track updated — your progress was kept' : `Track “${r.specialization}” created`)
      onApplied(r)
    } catch (e) { toast('err', (e as Error).message) } finally { setBusy(false) }
  }

  if (!open) return <div className="card row" style={{ justifyContent: 'space-between' }}>
    <div><h2 style={{ margin: 0 }}>Discuss this track</h2><p className="muted" style={{ margin: 0 }}>Ask the AI why it's planned this way, or tell it what to change.</p></div>
    <button onClick={() => setOpen(true)}><Icon name="chat" size={16} />Talk to the advisor</button></div>

  return (
    <div className="card">
      <div className="card-head"><div><h2>{design ? 'Create a new track with AI' : 'Roadmap advisor'}</h2>
        {design && <p className="muted" style={{ margin: 0 }}>Tell the AI what you want to learn. It runs alongside your other tracks and shares your study time.</p>}</div>
        <button className="ghost" onClick={() => (props.mode === 'design' ? props.onClose() : setOpen(false))}>Close</button></div>
      <ChatHistory sessions={chats.sessions} activeId={chats.activeId} busy={busy} onOpen={chats.open} onNew={chats.startNew} onDelete={chats.remove} />
      <div className="chat" style={{ maxHeight: 380, overflowY: 'auto' }} aria-live="polite">
        {!msgs.length && <div className="chips">{(design ? designStarters : discussStarters).map(s => <button key={s} className="chip" onClick={() => ask(s)}>{s}</button>)}</div>}
        {msgs.map((m, i) => {
          const all = m.proposal?.subjects.flatMap(s => s.chapters.map(c => c.title)) ?? []
          const added = track ? all.filter(t => !titles.has(t)) : []
          const removed = track ? [...titles].filter(t => !all.includes(t)) : []
          return (
            <Message key={i} me={m.me} text={m.text}>
              {m.proposal && <div className="proposal">
                  <b>{track ? 'Proposed' : 'New track'}: {m.proposal.specialization}</b>
                  <div className="muted">{m.proposal.subjects.length} subjects · {all.length} chapters · {Math.round(m.proposal.subjects.reduce((a, s) => a + s.chapters.reduce((h, c) => h + c.estimated_hours, 0), 0))}h</div>
                  {!track && m.proposal.subjects.map(s => <div key={s.name}><b>{s.name}</b><div className="muted">{s.chapters.map(c => c.title).join(' → ')}</div></div>)}
                  {added.length > 0 && <div>➕ {added.join('; ')}</div>}
                  {removed.length > 0 && <div>➖ {removed.join('; ')}</div>}
                  {track && !added.length && !removed.length && <div className="muted">Reorders or re-times existing chapters.</div>}
                  {m.applied ? <span className="badge green">{track ? 'Applied' : 'Created'}</span>
                    : <button disabled={busy} onClick={() => apply(i, m.proposal!)}>{track ? 'Apply changes' : 'Create track'}</button>}
                </div>}
            </Message>)
        })}
        {busy && <Typing />}
        <div ref={end} />
      </div>
      <Composer value={text} onChange={setText} onSend={ask} busy={busy}
        placeholder={design ? 'e.g. I want to learn guitar basics in 8 weeks…' : 'e.g. Add more practice problems…'} />
    </div>
  )
}
