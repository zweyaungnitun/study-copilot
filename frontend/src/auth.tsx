import { createContext, useContext, useState, type ReactNode } from 'react'
import { api, getSession, setSession, type Session } from './api'

interface Ctx {
  session: Session | null
  login: (u: string, p: string) => Promise<void>
  register: (u: string, p: string) => Promise<void>
  logout: () => void
}
const AuthCtx = createContext<Ctx>(null!)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, set] = useState<Session | null>(getSession())
  const store = (s: Session | null) => { setSession(s); set(s) }
  return (
    <AuthCtx.Provider value={{
      session,
      login: async (u, p) => store(await api.login(u, p)),
      register: async (u, p) => store(await api.register(u, p)),
      logout: () => store(null),
    }}>{children}</AuthCtx.Provider>
  )
}
