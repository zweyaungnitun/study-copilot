import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { Link, useSearchParams } from 'react-router-dom'
import { api, tutorStream, type AgentStep, type ChatMsg, type ChatSummary, type Citation, type TutorReply } from '../api'
import { useChats } from '../useChats'
import { useAuth } from '../auth'
import { useLoad } from '../hooks'
import { Icon, Markdown, Spinner, useToast, type IconName } from '../ui'

interface Msg {
  me: boolean; text: string; badges?: string[]; warn?: string; followUp?: string; suggestions?: string[]
  citations?: Citation[]; steps?: AgentStep[]; streaming?: boolean; stopped?: boolean
}

const starterIcons: IconName[] = ['bulb', 'target', 'alert', 'map']
const generalStarters = [
  ['Explain a concept', 'Explain this concept in simple terms'],
  ['Quiz me', 'Quiz me on what I just studied'],
  ['Check my answer', 'Why is my answer wrong?'],
  ['Plan my study', 'What should I focus on next?'],
]
const chapterStarters = (t: string) => [
  ['Explain simply', `Explain “${t}” in simple terms`],
  ['Quiz me', `Quiz me on “${t}”`],
  ['Common mistakes', `What are the most common mistakes in “${t}”?`],
  ['Real-world use', `Give me a real-world example of “${t}”`],
]
const HINTS: [number, string, string][] = [[1, 'Concept', 'A gentle conceptual nudge'], [2, 'Scaffold', 'Step-by-step scaffolding'], [3, 'Worked step', 'Shows a worked step']]

const toMsg = (m: ChatMsg): Msg => {
  const x = m.meta as { badges?: string[]; warn?: string; followUp?: string; citations?: Citation[]; steps?: AgentStep[] }
  return m.role === 'user' ? { me: true, text: m.content }
    : { me: false, text: m.content, badges: x.badges, warn: x.warn ?? undefined, followUp: x.followUp ?? undefined, citations: x.citations, steps: x.steps }
}

const fromReply = (r: TutorReply): Msg => ({
  me: false, text: r.reply, followUp: r.follow_up_question || undefined, suggestions: r.suggestions,
  badges: [r.source, `Hint ${r.hint_level}`].filter(Boolean), warn: r.detected_misconception || undefined,
  citations: r.citations, steps: r.steps,
})

/** What the agent did this turn: live while streaming, collapsible afterwards. */
function Activity({ steps, live }: { steps: AgentStep[]; live: boolean }) {
  const [open, setOpen] = useState(false)
  if (!steps.length) return null
  const show = live || open
  const list = <ul className="t-steps">{steps.map((s, i) => (
    <li key={i} className={s.status}>
      <span className="t-step-dot">{s.status === 'running' ? <Spinner /> : <Icon name={s.status === 'error' ? 'alert' : 'check'} size={12} />}</span>
      <span>{s.status === 'running' ? `${s.label}…` : s.summary || s.label}</span>
    </li>))}</ul>
  if (live) return list
  return <div className="t-activity">
    <button className="t-activity-btn" onClick={() => setOpen(o => !o)} aria-expanded={open}>
      <Icon name="tool" size={13} />Used {steps.length} tool{steps.length > 1 ? 's' : ''}<Icon name="chevron" size={12} /></button>
    {show && list}
  </div>
}

const ago = (iso: string) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso + 'Z').getTime()) / 60000))
  return m < 1 ? 'now' : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`
}
const isToday = (iso: string) => new Date(iso + 'Z').toDateString() === new Date().toDateString()

const Orb = ({ size = 32 }: { size?: number }) => (
  <span className="t-orb" style={{ width: size, height: size }} aria-hidden="true"><Icon name="spark" size={Math.round(size * 0.45)} /></span>
)

/* ---------- Conversation list ---------- */
function Conversations({ sessions, activeId, busy, onOpen, onNew, onDelete }: {
  sessions: ChatSummary[]; activeId: string | null; busy: boolean
  onOpen: (id: string) => void; onNew: () => void; onDelete: (id: string) => void
}) {
  const [q, setQ] = useState('')
  const groups = useMemo(() => {
    const f = sessions.filter(s => s.title.toLowerCase().includes(q.trim().toLowerCase()))
    return [['Today', f.filter(s => isToday(s.updated_at))], ['Earlier', f.filter(s => !isToday(s.updated_at))]] as const
  }, [sessions, q])
  return (
    <aside className="t-side" aria-label="Conversations">
      <button className="t-new" onClick={onNew} disabled={busy}><Icon name="plus" size={16} />New conversation</button>
      <label className="t-filter"><Icon name="search" size={14} />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search chats" aria-label="Search chats" /></label>
      <div className="t-convos">
        {!sessions.length && <p className="t-none">Your conversations are saved here automatically.</p>}
        {groups.map(([label, list]) => list.length > 0 && <div key={label}>
          <div className="t-group">{label}</div>
          {list.map(s => (
            <div key={s.id} className={`t-convo ${s.id === activeId ? 'on' : ''}`}>
              <button className="t-convo-open" onClick={() => onOpen(s.id)} disabled={busy}>
                <span className="t-convo-title">{s.title}</span>
                <span className="t-convo-meta">{s.message_count} msgs · {ago(s.updated_at)}</span>
              </button>
              <button className="t-convo-del" aria-label={`Delete chat ${s.title}`} title="Delete"
                onClick={() => { if (confirm('Delete this chat?')) onDelete(s.id) }}><Icon name="trash" size={14} /></button>
            </div>))}
        </div>)}
      </div>
    </aside>
  )
}

/* ---------- One message ---------- */
function Bubble({ m, onAsk }: { m: Msg; onAsk: (s: string) => void }) {
  const toast = useToast()
  if (m.me) return <div className="t-row me"><div className="t-msg me">{m.text}</div></div>
  const copy = async () => { try { await navigator.clipboard.writeText(m.text); toast('ok', 'Copied to clipboard') } catch { toast('err', 'Could not copy') } }
  return (
    <div className="t-row">
      <Orb size={30} />
      <div className={`t-msg ai ${m.streaming ? 'streaming' : ''}`}>
        <Activity steps={m.steps ?? []} live={!!m.streaming && !m.text} />
        {m.streaming && !m.text && !(m.steps ?? []).some(s => s.status === 'running') &&
          <div className="t-thinking" role="status"><span className="t-dots"><i /><i /><i /></span>Thinking…</div>}
        {m.text && <Markdown text={m.text} />}
        {m.stopped && <p className="t-stopped">Stopped</p>}
        {!m.streaming && !!m.citations?.length && <div className="t-sources">
          <span className="t-sources-label">Sources</span>
          {m.citations.map(c => <span key={c.n} className="t-source" title={c.snippet}><b>{c.n}</b>{c.filename}<em>p.{c.page}</em></span>)}
        </div>}
        {!m.streaming && m.warn && <div className="t-warn"><Icon name="alert" size={14} /><span><b>Possible misconception:</b> {m.warn}</span></div>}
        {!m.streaming && m.followUp && <button className="t-followup" onClick={() => onAsk(m.followUp!)}>
          <span className="t-followup-tag"><Icon name="bulb" size={13} />Try this</span><span>{m.followUp}</span></button>}
        {!m.streaming && <div className="t-msg-foot">
          {m.badges?.map(b => <span key={b} className="t-tag">{b}</span>)}
          <button className="t-icon" onClick={copy} title="Copy" aria-label="Copy reply"><Icon name="copy" size={14} /></button>
        </div>}
      </div>
    </div>
  )
}

export default function Tutor() {
  const { session } = useAuth()
  const [params] = useSearchParams()
  const chapterId = params.get('chapter')
  const chats = useChats<Msg>(session!.user_id, 'tutor', chapterId, toMsg)
  const { msgs, setMsgs } = chats
  const [text, setText] = useState('')
  const [hint, setHint] = useState(1)
  const [mode, setMode] = useState<'socratic' | 'direct'>('socratic')
  const [busy, setBusy] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const chapter = useLoad(async () => (chapterId ? api.chapter(chapterId) : null), [chapterId])
  const starters = chapter.data ? chapterStarters(chapter.data.title) : generalStarters
  const scroller = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const abort = useRef<AbortController | null>(null)
  const stick = useRef(true)

  // Follow new text only while the learner is at the bottom, so scrolling up to reread isn't hijacked.
  const onScroll = () => { const el = scroller.current; if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120 }
  useEffect(() => { const el = scroller.current; if (el && stick.current) el.scrollTop = el.scrollHeight }, [msgs, busy])
  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => {
    const el = input.current; if (!el) return
    el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [text])

  const ask = async (message: string) => {
    message = message.trim(); if (!message || busy) return
    stick.current = true
    setMsgs(m => [...m.map(x => ({ ...x, suggestions: undefined })), { me: true, text: message }, { me: false, text: '', steps: [], streaming: true }])
    setText(''); setBusy(true)
    // Patch the in-flight assistant message (always the last one).
    const patch = (f: (x: Msg) => Msg) => setMsgs(m => m.length ? [...m.slice(0, -1), f(m[m.length - 1])] : m)
    const ctrl = new AbortController(); abort.current = ctrl
    let gotText = false
    try {
      const session_id = await chats.ensure()
      const body = { user_id: session!.user_id, message, hint_level: hint, mode, chapter_id: chapterId || undefined, session_id }
      let r: TutorReply
      try {
        r = await tutorStream(body, ev => {
          if (ev.type === 'delta') { gotText = true; patch(x => ({ ...x, text: x.text + ev.text })) }
          else if (ev.type === 'reset') patch(x => ({ ...x, text: '' }))
          else if (ev.type === 'step') patch(x => { const st = [...(x.steps ?? [])]; st[ev.index] = ev; return { ...x, steps: st } })
        }, ctrl.signal)
      } catch (e) {
        if (ctrl.signal.aborted || gotText) throw e
        r = await api.tutor(body)  // stream unavailable (proxy, old server): fall back to one JSON reply
      }
      patch(() => fromReply(r))
      chats.refresh()
    } catch (x) {
      if (ctrl.signal.aborted) patch(m => ({ ...m, streaming: false, stopped: true, steps: (m.steps ?? []).filter(s => s.status !== 'running') }))
      else patch(m => ({ ...m, streaming: false, text: m.text || `Sorry — ${(x as Error).message}` }))
    }
    finally { abort.current = null; setBusy(false); input.current?.focus() }
  }
  const stop = () => abort.current?.abort()
  const submit = (e?: FormEvent) => { e?.preventDefault(); ask(text) }
  const onKey = (e: KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) submit(e) }
  const pick = (fn: () => void) => () => { fn(); setDrawer(false) }

  const last = msgs[msgs.length - 1]
  const suggestions = !busy && last && !last.me ? last.suggestions ?? [] : []
  const title = chats.sessions.find(s => s.id === chats.activeId)?.title ?? 'New conversation'

  const convos = <Conversations sessions={chats.sessions} activeId={chats.activeId} busy={busy}
    onOpen={id => { chats.open(id); setDrawer(false) }} onNew={pick(chats.startNew)} onDelete={chats.remove} />

  return (
    <div className="tutor">
      {convos}
      {drawer && createPortal(<div className="t-drawer"><div className="t-scrim" onClick={() => setDrawer(false)} />{convos}</div>, document.body)}

      <section className="t-main">
        <header className="t-head">
          <button className="t-icon t-drawer-btn" onClick={() => setDrawer(true)} aria-label="Show conversations"><Icon name="list" size={18} /></button>
          <Orb size={38} />
          <div className="t-head-text">
            <h1>{msgs.length ? title : 'AI Tutor'}</h1>
            <p><span className="t-live" />{chapterId
              ? <>Focused on <Link to={`/chapters/${chapterId}`}>{chapter.data?.title ?? 'your chapter'}</Link></>
              : 'Guides you to the answer, not just to it'}</p>
          </div>
          <div className="t-mode" role="radiogroup" aria-label="Tutor style">
            {(['socratic', 'direct'] as const).map(v => (
              <button key={v} role="radio" aria-checked={mode === v} className={mode === v ? 'on' : ''} onClick={() => setMode(v)}
                title={v === 'socratic' ? 'Guides you with questions' : 'Gives direct answers'}>{v === 'socratic' ? 'Socratic' : 'Direct'}</button>))}
          </div>
        </header>

        <div className="t-scroll" ref={scroller} onScroll={onScroll} aria-live="polite">
          {!msgs.length && !chats.loading && <div className="t-welcome">
            <div className="t-hero-orb"><Orb size={64} /></div>
            <h2>Hi {session!.username}, what are we learning today?</h2>
            <p className="muted">{chapter.data ? <>I’ve read your notes on <b>{chapter.data.title}</b>. Pick a starting point or ask anything.</> : 'Ask a question, paste a problem, or pick a starting point.'}</p>
            <div className="t-starters">
              {starters.map(([label, prompt], i) => (
                <button key={prompt} className="t-starter" onClick={() => ask(prompt)} style={{ animationDelay: `${0.05 * i}s` }}>
                  <span className="t-starter-icon"><Icon name={starterIcons[i]} size={16} /></span>
                  <b>{label}</b><span>{prompt}</span></button>))}
            </div>
          </div>}
          {chats.loading && !msgs.length && <div className="t-welcome"><Spinner /></div>}
          <div className="t-thread">
            {msgs.map((m, i) => <Bubble key={i} m={m} onAsk={ask} />)}
            {suggestions.length > 0 && <div className="t-suggest">{suggestions.map(s => <button key={s} onClick={() => ask(s)}>{s}<Icon name="arrow" size={13} /></button>)}</div>}
          </div>
        </div>

        <form className="t-composer" onSubmit={submit}>
          <div className="t-box">
            <textarea ref={input} rows={1} aria-label="Message" value={text} autoFocus placeholder={mode === 'socratic' ? 'Ask a question — I’ll guide you there…' : 'Ask anything…'}
              onChange={e => setText(e.target.value)} onKeyDown={onKey} />
            <div className="t-box-bar">
              <div className="t-hints" role="radiogroup" aria-label="Hint level">
                {HINTS.map(([v, l, d]) => (
                  <button type="button" key={v} role="radio" aria-checked={hint === v} className={hint === v ? 'on' : ''} onClick={() => setHint(v)} title={d}>
                    <span className="t-pips">{[1, 2, 3].map(n => <i key={n} className={n <= v ? 'f' : ''} />)}</span><span className="t-hint-label">{l}</span></button>))}
              </div>
              {busy
                ? <button type="button" className="t-send stop" onClick={stop} aria-label="Stop generating" title="Stop"><Icon name="stop" size={14} /></button>
                : <button className="t-send" disabled={!text.trim()} aria-label="Send"><Icon name="send" size={16} /></button>}
            </div>
          </div>
          <p className="t-foot">Enter to send · Shift+Enter for a new line</p>
        </form>
      </section>
    </div>
  )
}
