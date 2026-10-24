import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, getSession, setSession, type Session } from './api'

interface Ctx {
  session: Session | null
  isAdmin: boolean
  login: (u: string, p: string) => Promise<void>
  register: (u: string, p: string) => Promise<void>
  logout: () => void
}
const AuthCtx = createContext<Ctx>(null!)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, set] = useState<Session | null>(getSession())
  const store = (s: Session | null) => { setSession(s); set(s) }

  // Expired/invalid tokens (e.g. issued before tokens were signed) end the session.
  useEffect(() => {
    const out = () => store(null)
    window.addEventListener('sp:unauthorized', out)
    return () => window.removeEventListener('sp:unauthorized', out)
  }, [])

  // Refresh the role from the server so promotions/demotions apply without a fresh login.
  const token = session?.token
  useEffect(() => {
    if (!token) return
    api.me().then(me => {
      const cur = getSession()
      if (cur && cur.token === token && cur.role !== me.role) store({ ...cur, role: me.role })
    }).catch(() => { /* 401 is handled by the listener above */ })
  }, [token])

  return (
    <AuthCtx.Provider value={{
      session,
      isAdmin: session?.role === 'admin',
      login: async (u, p) => store(await api.login(u, p)),
      register: async (u, p) => store(await api.register(u, p)),
      logout: () => store(null),
    }}>{children}</AuthCtx.Provider>
  )
}
