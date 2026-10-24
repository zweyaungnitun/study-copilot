import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type ChatMsg, type ChatSummary } from './api'

/**
 * Saved chat sessions for one kind of conversation. Opens the most recent chat for the scope
 * (a chapter, or none) and creates a new session lazily on the first message.
 */
export function useChats<T>(userId: string, kind: 'tutor' | 'roadmap' | 'design', chapterId: string | null, toMsg: (m: ChatMsg) => T) {
  const [sessions, setSessions] = useState<ChatSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<T[]>([])
  const [loading, setLoading] = useState(true)
  const convert = useRef(toMsg); convert.current = toMsg

  const open = useCallback(async (id: string) => {
    const d = await api.chat(id, userId)
    setActiveId(id); setMsgs(d.messages.map(convert.current))
  }, [userId])

  useEffect(() => {
    let live = true
    setLoading(true)
    api.chats(userId, kind).then(async all => {
      if (!live) return
      setSessions(all)
      // Resume the latest chat for this scope; otherwise start fresh.
      const scoped = all.find(s => (s.chapter_id ?? null) === chapterId && s.message_count > 0)
      if (scoped) await open(scoped.id); else { setActiveId(null); setMsgs([]) }
    }).catch(() => { /* history is optional; chat still works */ }).finally(() => live && setLoading(false))
    return () => { live = false }
  }, [userId, kind, chapterId, open])

  /** Returns the active session id, creating one if needed. */
  const ensure = async () => {
    if (activeId) return activeId
    const s = await api.newChat(userId, kind, chapterId ?? undefined)
    setActiveId(s.id); setSessions(x => [s, ...x])
    return s.id
  }
  /** Re-fetch the list so titles, counts and ordering stay current. */
  const refresh = async () => { try { setSessions(await api.chats(userId, kind)) } catch { /* ignore */ } }
  const startNew = () => { setActiveId(null); setMsgs([]) }
  const remove = async (id: string) => {
    await api.deleteChat(id, userId)
    setSessions(x => x.filter(s => s.id !== id))
    if (id === activeId) startNew()
  }
  return { sessions, activeId, msgs, setMsgs, loading, open, ensure, refresh, startNew, remove }
}
