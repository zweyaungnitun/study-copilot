import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Icon, PageHeader, Spinner } from '../ui'

interface Msg { me: boolean; text: string; badges?: string[]; warn?: string }
const suggestions = ['Explain this concept in simple terms', 'Quiz me on what I just studied', 'Why is my answer wrong?']

export default function Tutor() {
  const { session } = useAuth()
  const [params] = useSearchParams()
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const [hint, setHint] = useState(1)
  const [mode, setMode] = useState('socratic')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs, busy])

  const ask = async (message: string) => {
    message = message.trim(); if (!message || busy) return
    setMsgs(m => [...m, { me: true, text: message }]); setText(''); setBusy(true)
    try {
      const r = await api.tutor({ user_id: session!.user_id, message, hint_level: hint, mode, chapter_id: params.get('chapter') || undefined })
      setMsgs(m => [...m, { me: false, text: r.reply + (r.follow_up_question ? `\n\n${r.follow_up_question}` : ''), badges: [r.source, `Hint ${r.hint_level}`].filter(Boolean), warn: r.detected_misconception }])
    } catch (x) { setMsgs(m => [...m, { me: false, text: `Sorry — ${(x as Error).message}` }]) }
    finally { setBusy(false) }
  }
  const send = (e: FormEvent) => { e.preventDefault(); ask(text) }

  return (
    <>
      <PageHeader title="AI Tutor" sub={params.get('chapter') ? 'Focused on your selected chapter.' : 'Ask anything — get guided, not just answered.'} />
      <div className="card chat-shell">
        <div className="chat-toolbar">
          <select aria-label="Tutor style" value={mode} onChange={e => setMode(e.target.value)}>
            <option value="socratic">Socratic · guides you</option><option value="direct">Direct · gives answers</option></select>
          <select aria-label="Hint level" value={hint} onChange={e => setHint(+e.target.value)}>
            <option value={1}>Hint 1 · Conceptual</option><option value={2}>Hint 2 · Scaffolded</option><option value={3}>Hint 3 · Worked step</option></select>
        </div>
        <div className="chat" aria-live="polite">
          {!msgs.length && <div className="chat-empty">
            <span className="empty-icon"><Icon name="chat" size={24} /></span><h2>How can I help you study?</h2>
            <p className="muted">Ask a question, or try one of these:</p>
            <div className="chips">{suggestions.map(s => <button key={s} className="chip" onClick={() => ask(s)}>{s}</button>)}</div></div>}
          {msgs.map((m, i) => (
            <div key={i} className={`msg-row ${m.me ? 'me' : ''}`}>
              {!m.me && <span className="msg-avatar"><Icon name="spark" size={14} /></span>}
              <div className={`msg ${m.me ? 'me' : ''}`}>{m.text}
                {(m.badges?.length || m.warn) && <div className="badges">
                  {m.badges?.map(b => <span key={b} className="badge gray">{b}</span>)}
                  {m.warn && <span className="badge yellow"><Icon name="alert" size={12} />{m.warn}</span>}</div>}</div>
            </div>))}
          {busy && <div className="msg-row"><span className="msg-avatar"><Icon name="spark" size={14} /></span><div className="msg"><span className="typing"><i /><i /><i /></span></div></div>}
          <div ref={end} />
        </div>
        <form className="composer" onSubmit={send}>
          <input aria-label="Message" value={text} onChange={e => setText(e.target.value)} placeholder="Ask a question…" autoFocus />
          <button disabled={busy || !text.trim()} aria-label="Send">{busy ? <Spinner /> : <Icon name="send" size={16} />}<span className="desktop-only">Send</span></button>
        </form>
      </div>
    </>
  )
}
