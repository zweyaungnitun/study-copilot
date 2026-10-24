import { useState } from 'react'
import type { ChatSummary } from './api'
import { Icon } from './ui'

const ago = (iso: string) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso + 'Z').getTime()) / 60000))
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`
}

/** Saved-chat switcher: list, open, start new and delete conversations. */
export default function ChatHistory({ sessions, activeId, onOpen, onNew, onDelete, busy }: {
  sessions: ChatSummary[]; activeId: string | null; busy?: boolean
  onOpen: (id: string) => void; onNew: () => void; onDelete: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const active = sessions.find(s => s.id === activeId)
  return (
    <div className="chat-history">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <button className="ghost" onClick={() => setOpen(o => !o)} aria-expanded={open}>
          <Icon name="book" size={16} />{active ? active.title : 'New chat'} · {sessions.length} saved</button>
        <button className="ghost" disabled={busy} onClick={() => { setOpen(false); onNew() }}><Icon name="refresh" size={16} />New chat</button>
      </div>
      {open && <div className="list chat-history-list">
        {!sessions.length && <p className="muted" style={{ padding: 12 }}>No saved chats yet — your conversations are saved automatically.</p>}
        {sessions.map(s => (
          <div key={s.id} className={`item ${s.id === activeId ? 'active' : ''}`}>
            <button className="linklike grow" onClick={() => { setOpen(false); onOpen(s.id) }}>
              <div className="title">{s.title}</div><div className="muted">{ago(s.updated_at)} · {s.message_count} messages</div></button>
            <button className="ghost" aria-label={`Delete chat ${s.title}`} onClick={() => { if (confirm('Delete this chat?')) onDelete(s.id) }}>Delete</button>
          </div>))}
      </div>}
    </div>
  )
}
