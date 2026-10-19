const BASE = '/api'

export interface Session { user_id: string; username: string; token: string }

export function getSession(): Session | null {
  try { return JSON.parse(localStorage.getItem('sp_session') || 'null') } catch { return null }
}
export function setSession(s: Session | null) {
  if (s) localStorage.setItem('sp_session', JSON.stringify(s))
  else localStorage.removeItem('sp_session')
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const s = getSession()
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
  if (!(init.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  if (s) headers.Authorization = `Bearer ${s.token}`
  const res = await fetch(BASE + path, { ...init, headers })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const d = await res.json()
      msg = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail ?? d)
    } catch { /* ignore */ }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

const get = <T,>(p: string) => request<T>(p)
const post = <T,>(p: string, body?: unknown) =>
  request<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const qs = (o: Record<string, string | number | boolean | undefined>) =>
  '?' + Object.entries(o).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')

export interface Chapter { id: string; title: string; estimated_hours: number; status: string; mastery_score: number }
export interface Subject { id: string; name: string; order_index: number; chapters: Chapter[] }
export interface Roadmap { id: string; specialization: string; total_estimated_hours: number; subjects: Subject[] }
export interface Flashcard { id: string; chapter_id: string; type: string; front: string; back: string; source: string; source_citation?: string }
export interface ReviewResult { interval: number; ease: number; reps: number; next_review: string }
export interface Note { chapter_id: string; simple_content: string; detailed_content: string; exam_content: string; cheat_sheet?: string }
export interface Task { id: string; type: string; title: string; estimated_minutes: number; chapter_id?: string }
export interface SessionStart { session_id: string; energy_level: string; tasks: Task[] }
export interface SessionEnd { streak_updated: number; xp_earned: number; message: string }
export interface TutorReply { reply: string; source: string; hint_level: number; detected_misconception?: string; follow_up_question?: string }
export interface BrainNode { id: string; label: string; status: string; retention_score: number; color: string; mastery_percentage: number }
export interface BrainMap { nodes: BrainNode[]; edges: { source: string; target: string }[]; overall_retention_average: number; total_nodes: number; at_risk_count: number }
export interface Material { id: string; filename: string; file_type: string; chunk_count: number; status: string }
export interface RAGResult { badge: string; is_grounded_in_notes: boolean; context_text: string; sources: { citation: string; score: number }[] }
export interface Mistake { id: string; chapter_id: string; question: string; student_answer: string; correct_answer: string; explanation: string; misconception_tag?: string }
export interface Coach { report_markdown: string; stats: { current_streak: number; total_xp: number; total_sessions: number; total_minutes: number; unresolved_mistakes: number } }
export interface LeaderEntry { rank: number; user_id: string; username: string; streak_days: number; sessions_completed: number; consistency_score: number }
export interface DiagQ { id: string; question: string; options: string[] }
export interface DiagResult { score_percentage: number; calibrated_level: string; strengths: string[]; identified_weaknesses: string[]; recommended_focus: string }

export const api = {
  register: (username: string, password: string) => post<Session>('/auth/register', { username, password }),
  login: (username: string, password: string) => post<Session>('/auth/login', { username, password }),
  saveProfile: (b: Record<string, unknown>) => post('/intake/profile', b),
  diagnostic: (goal: string, level: string) => post<DiagQ[]>('/intake/diagnostic', { goal, level }),
  submitDiagnostic: (user_id: string, goal: string, answers: { question_id: string; selected_option_index: number }[]) =>
    post<DiagResult>('/intake/diagnostic/submit', { user_id, goal, answers }),
  generateRoadmap: (user_id: string) => post<Roadmap>('/roadmap/generate', { user_id }),
  roadmap: (user_id: string) => get<Roadmap>('/roadmap/current' + qs({ user_id })),
  notes: (chapter_id: string) => get<Note>(`/chapters/${chapter_id}/notes`),
  genCards: (chapter_id: string, count = 10) => post<Flashcard[]>('/flashcards/generate', { chapter_id, count }),
  dueCards: (user_id: string, limit = 20) => get<Flashcard[]>('/flashcards/due' + qs({ user_id, limit })),
  review: (id: string, quality: number) => post<ReviewResult>(`/flashcards/${id}/review`, { quality }),
  startSession: (user_id: string, energy_level: string) => post<SessionStart>('/session/start', { user_id, energy_level }),
  endSession: (b: Record<string, unknown>) => post<SessionEnd>('/session/end', b),
  tutor: (b: Record<string, unknown>) => post<TutorReply>('/tutor/chat', b),
  brainMap: (user_id: string) => get<BrainMap>('/brain-map' + qs({ user_id })),
  materials: (user_id: string) => get<Material[]>(`/materials/user/${user_id}`),
  upload: (user_id: string, file: File) => {
    const f = new FormData(); f.append('user_id', user_id); f.append('file', file)
    return request<Material>('/materials/upload', { method: 'POST', body: f })
  },
  queryMaterials: (user_id: string, query: string) => post<RAGResult>('/materials/query', { user_id, query }),
  mistakes: (user_id: string) => get<Mistake[]>('/mistakes' + qs({ user_id, resolved: false })),
  resolveMistake: (id: string) => post(`/mistakes/${id}/resolve`),
  coach: (user_id: string) => get<Coach>('/coach/weekly-report' + qs({ user_id })),
  leaderboard: () => get<{ total_participants: number; rankings: LeaderEntry[] }>('/leaderboard'),
}
