import { useEffect, useRef, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { Icon, Markdown, Spinner } from './ui'

export const Avatar = () => <span className="msg-avatar" aria-hidden="true"><Icon name="spark" size={14} /></span>

export const Typing = () => (
  <div className="msg-row"><Avatar /><div className="msg ai"><span className="typing" role="status" aria-label="AI is typing"><i /><i /><i /></span></div></div>
)

/** One chat message. AI replies render as Markdown on the page background; the learner's are a soft bubble. */
export function Message({ me, text, children }: { me: boolean; text: string; children?: ReactNode }) {
  return (
    <div className={`msg-row ${me ? 'me' : ''}`}>
      {!me && <Avatar />}
      <div className={`msg ${me ? 'me' : 'ai'}`}>{me ? text : <Markdown text={text} />}{children}</div>
    </div>
  )
}

/** Auto-growing composer: Enter sends, Shift+Enter adds a new line. */
export function Composer({ value, onChange, onSend, busy, placeholder, autoFocus }: {
  value: string; onChange: (v: string) => void; onSend: (v: string) => void; busy: boolean; placeholder: string; autoFocus?: boolean
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const el = ref.current; if (!el) return
    el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [value])
  const submit = (e?: FormEvent) => { e?.preventDefault(); if (value.trim() && !busy) onSend(value) }
  const key = (e: KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) submit(e) }
  return (
    <form className="composer" onSubmit={submit}>
      <div className="composer-box">
        <textarea ref={ref} rows={1} aria-label="Message" value={value} placeholder={placeholder} autoFocus={autoFocus}
          onChange={e => onChange(e.target.value)} onKeyDown={key} />
        <button className="send" disabled={busy || !value.trim()} aria-label="Send">{busy ? <Spinner /> : <Icon name="send" size={16} />}</button>
      </div>
      <p className="composer-hint">Enter to send · Shift+Enter for a new line</p>
    </form>
  )
}
