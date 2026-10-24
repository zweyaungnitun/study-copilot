const BASE = '/api'

export interface Session { user_id: string; username: string; token: string; role?: 'student' | 'admin' }

export function getSession(): Session | null {
  try { return JSON.parse(localStorage.getItem('sp_session') || 'null') } catch { return null }
}
export function setSession(s: Session | null) {
  if (s) localStorage.setItem('sp_session', JSON.stringify(s))
  else localStorage.removeItem('sp_session')
}

/** Server timestamps are naive UTC; parse them as UTC. */
export const utc = (iso: string) => new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')

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
  // An expired/invalid token on a protected route ends the session (AuthProvider listens for this).
  if (res.status === 401 && s && !path.startsWith('/auth/login')) window.dispatchEvent(new Event('sp:unauthorized'))
  if (!res.ok) {
    let msg = res.statusText
    try {
      const d = await res.json()
      msg = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail ?? d)
    } catch { /* ignore */ }
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const get = <T,>(p: string) => request<T>(p)
const patch = <T,>(p: string, body: unknown) => request<T>(p, { method: 'PATCH', body: JSON.stringify(body) })
const put = <T,>(p: string, body: unknown) => request<T>(p, { method: 'PUT', body: JSON.stringify(body) })
const post = <T,>(p: string, body?: unknown) =>
  request<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const qs = (o: Record<string, string | number | boolean | undefined>) =>
  '?' + Object.entries(o).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')

export interface Chapter { id: string; title: string; estimated_hours: number; status: string; mastery_score: number; prerequisites: string[] }
export interface ChapterRef { id: string; title: string; status: string }
export interface ChapterSource { section_id: string; material_id: string; filename: string; title: string; page_start: number; page_end: number }
export interface ChapterDetail { id: string; roadmap_id: string; roadmap_name: string; title: string; subject_name: string; estimated_hours: number; status: string; mastery_score: number; prerequisites: ChapterRef[]; next_chapter: ChapterRef | null; sources?: ChapterSource[] }
export interface ChapterComplete { chapter: ChapterDetail; unlocked: { id: string; title: string }[] }
export interface TutorTurn { role: 'user' | 'tutor'; content: string }
export interface Subject { id: string; name: string; order_index: number; chapters: Chapter[] }
export interface Roadmap { id: string; specialization: string; total_estimated_hours: number; subjects: Subject[] }
export interface ProposalSource { section_id: string; title: string; filename: string; page_start: number; page_end: number; hours: number }
export interface ProposalChapter { title: string; estimated_hours: number; prerequisites: string[]; source_section_ids?: string[]; sources?: ProposalSource[] }
export interface Proposal { specialization: string; subjects: { name: string; chapters: ProposalChapter[] }[] }
export interface DiscussReply { reply: string; proposal: Proposal | null; session_id?: string; message_id?: string }
export interface ChatSummary { id: string; kind: 'tutor' | 'roadmap' | 'design'; chapter_id?: string; title: string; updated_at: string; message_count: number }
export interface ChatMsg { id: string; role: 'user' | 'ai'; content: string; meta: Record<string, unknown>; created_at: string }
export interface ChatDetail extends ChatSummary { messages: ChatMsg[] }
export interface ResourceLink { id: string; type: string; label: string; url: string; source: 'ai' | 'search' | 'user' }
export interface StudyGuide { chapter_id: string; overview: string; objectives: string[]; lesson_steps: { title: string; minutes: number; activity: string }[]; practice: string[]; resources: ResourceLink[] }
export interface Note { chapter_id: string; simple_content: string; detailed_content: string; exam_content: string; cheat_sheet?: string }
export interface Task { id: string; type: string; title: string; estimated_minutes: number; chapter_id?: string }
export interface SessionStart { session_id: string; energy_level: string; tasks: Task[] }
export interface SessionEnd { streak_updated: number; xp_earned: number; message: string }
export interface Citation { n: number; filename: string; page: number; snippet: string }
export interface AgentStep { tool: string; label: string; status: 'running' | 'done' | 'error' | string; summary: string }
export interface TutorReply { session_id?: string; message_id?: string; reply: string; source: string; hint_level: number; detected_misconception?: string; follow_up_question?: string; suggestions?: string[]; citations?: Citation[]; steps?: AgentStep[]; agent?: boolean }
export type TutorEvent =
  | ({ type: 'step'; index: number } & AgentStep)
  | { type: 'delta'; text: string }
  | { type: 'reset' }
  | { type: 'done'; response: TutorReply }
  | { type: 'error'; message: string }

/** Streams one tutor turn over SSE, calling onEvent for each event; resolves with the final reply. */
export async function tutorStream(body: Record<string, unknown>, onEvent: (e: TutorEvent) => void, signal?: AbortSignal): Promise<TutorReply> {
  const s = getSession()
  const res = await fetch(BASE + '/tutor/chat/stream', {
    method: 'POST', body: JSON.stringify(body), signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(s ? { Authorization: `Bearer ${s.token}` } : {}) },
  })
  if (!res.ok || !res.body) {
    let msg = res.statusText
    try { const d = await res.json(); msg = typeof d.detail === 'string' ? d.detail : msg } catch { /* ignore */ }
    throw new ApiError(res.status, msg)
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  let final: TutorReply | null = null
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i); buf = buf.slice(i + 2)
      const data = block.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()).join('\n')
      if (!data) continue
      const ev = JSON.parse(data) as TutorEvent
      if (ev.type === 'error') throw new ApiError(500, ev.message)
      if (ev.type === 'done') final = ev.response
      onEvent(ev)
    }
  }
  if (!final) throw new ApiError(500, 'The tutor stream ended early')
  return final
}
export interface BrainNode { track?: string; id: string; label: string; status: string; retention_score: number; color: string; mastery_percentage: number }
export interface BrainMap { nodes: BrainNode[]; edges: { source: string; target: string }[]; overall_retention_average: number; total_nodes: number; at_risk_count: number }
export type MaterialStatus = 'pending' | 'extracting' | 'outlining' | 'embedding' | 'ready' | 'failed'
export interface Material { id: string; user_id: string; filename: string; file_type: string; file_size_bytes: number; chunk_count: number; status: MaterialStatus; progress: number; page_count: number; ocr_pages: number; outline_source?: string | null; error?: string | null; created_at: string; processed_at?: string | null; duplicate?: boolean }
export const PROCESSING: MaterialStatus[] = ['pending', 'extracting', 'outlining', 'embedding']
export interface Section { id: string; parent_id?: string | null; level: number; order: number; title: string; page_start: number; page_end: number; word_count: number; summary?: string | null; key_concepts: string[] }
export interface Storage { pages_used: number; page_limit: number; unlimited: boolean; custom_limit: boolean }
export interface SkippedSection { section_id: string; title: string; filename: string; hours: number; reason?: string | null }
export interface CurriculumUnit { section_id: string; title: string; filename: string; part: string; page_start: number; page_end: number; hours: number; skipped: boolean }
export interface CurriculumPreview { proposal: Proposal; method: 'llm' | 'fallback'; total_hours: number; budget_hours: number; over_budget: boolean; skipped: SkippedSection[]; suggested_skips: SkippedSection[]; units: CurriculumUnit[] }
export interface FromMaterialsBody { material_ids: string[]; goal?: string; deadline?: string; hours_per_day?: number; level?: string; skip_section_ids?: string[] | null; preferences?: string }
export type TaskKind = 'learn' | 'review' | 'practice' | 'buffer' | 'mock'
export interface ScheduledTask { id: string; date: string; order: number; kind: TaskKind; title: string; minutes: number; status: 'pending' | 'done' | 'skipped' | 'missed'; chapter_id?: string | null; roadmap_id?: string | null }
export interface ScheduleSummary { deadline: string; hours_per_day: number; daily_minutes: number; study_days: number; buffer_days: number; final_days: number; unscheduled_minutes: number; over_capacity: boolean; suggested_hours_per_day?: number | null; missed_tasks: number; explanation: string }
export interface Schedule { summary: ScheduleSummary | null; tasks: ScheduledTask[] }
export interface RAGResult { badge: string; is_grounded_in_notes: boolean; context_text: string; sources: { citation: string; score: number }[] }
export interface Mistake { id: string; chapter_id: string; question: string; student_answer: string; correct_answer: string; explanation: string; misconception_tag?: string }
export interface Coach { report_markdown: string; stats: { current_streak: number; total_xp: number; total_sessions: number; total_minutes: number; unresolved_mistakes: number } }
export interface LeaderEntry { rank: number; user_id: string; username: string; streak_days: number; sessions_completed: number; consistency_score: number }
export interface DiagQ { id: string; question: string; options: string[] }
export interface DiagResult { score_percentage: number; calibrated_level: string; strengths: string[]; identified_weaknesses: string[]; recommended_focus: string }


/* ---------- Mock exams & proctoring ---------- */
export interface ExamQuestion { id: string; chapter_id: string; chapter_title: string; question: string; options: string[]; points: number }
export interface Exam { exam_id: string; title: string; time_limit_minutes: number; started_at: string; is_exam_mode_active: boolean; questions: ExamQuestion[] }
export interface ExamResult { exam_id: string; total_questions: number; score: number; max_score: number; percentage: number; passed: boolean; time_taken_seconds?: number; points_lost_by_category: { chapter_title: string; points_lost: number; recommendation: string }[]; overall_feedback: string; integrity_score?: number; flag_count?: number }
export type ProctorEventType = 'tab_hidden' | 'window_blur' | 'fullscreen_exit' | 'fullscreen_enter' | 'copy' | 'paste' | 'context_menu' | 'print_screen' | 'multiple_screens' | 'exam_started'
export interface ProctorBeat { status: 'in_progress' | 'submitted' | 'terminated'; warning?: string | null; termination_reason?: string | null; integrity_score: number }
export type Risk = 'low' | 'medium' | 'high'
export interface Attempt { id: string; user_id: string; username: string; title: string; status: 'in_progress' | 'submitted' | 'terminated'; started_at: string; submitted_at?: string | null; time_limit_minutes: number; question_count: number; score?: number | null; percentage?: number | null; integrity_score: number; risk: Risk; flag_count: number; live: boolean; overdue: boolean; last_heartbeat_at?: string | null; termination_reason?: string | null; review_verdict?: 'cleared' | 'confirmed' | null; review_note?: string | null }
export interface ProctorEvent { id: string; type: string; detail?: string | null; weight: number; created_at: string }

/* ---------- Token usage ---------- */
export interface Quota { used: number; limit: number; remaining: number | null; percent: number; unlimited: boolean; custom_limit: boolean; period_start: string; resets_at: string }
export interface DailyUsage { date: string; tokens: number; calls: number }
export interface UsageSlice { key: string; tokens: number; calls: number }
export interface MyUsage { quota: Quota; daily: DailyUsage[]; by_feature: UsageSlice[] }

/* ---------- Admin ---------- */
export interface AdminUser { id: string; username: string; email?: string | null; role: 'student' | 'admin'; created_at: string; tokens_used: number; token_limit: number; custom_limit: boolean; percent: number; exams_taken: number; pages_used: number; page_limit: number; custom_page_limit: boolean }
export interface AdminMaterial extends Material { username: string }
export interface AdminMaterialsReport { default_page_limit: number; total_pages: number; counts: Record<string, number>; materials: AdminMaterial[] }
export interface AdminStats { total_users: number; new_users_7d: number; active_users_7d: number; admins: number; exams_total: number; exams_live: number; exams_flagged_unreviewed: number; avg_integrity_30d: number | null; tokens_this_period: number; tokens_today: number; users_over_quota: number; users_near_quota: number; default_token_limit: number }
export interface AdminOverview { stats: AdminStats; daily_tokens: DailyUsage[]; top_consumers: AdminUser[]; recent_flagged: Attempt[]; live_exams: Attempt[] }
export interface AdminTokenReport { period_start: string; resets_at: string; default_monthly_limit: number; total_tokens: number; total_calls: number; unattributed_tokens: number; daily: DailyUsage[]; by_feature: UsageSlice[]; by_model: UsageSlice[]; users: AdminUser[] }

export const admin = {
  overview: () => get<AdminOverview>('/admin/overview'),
  users: (q?: string) => get<AdminUser[]>('/admin/users' + qs({ q: q || undefined })),
  /** token_limit: number overrides the default (0 = unlimited); null restores the platform default. */
  updateUser: (id: string, b: { role?: 'student' | 'admin'; token_limit?: number | null; storage_page_limit?: number | null }) => patch<AdminUser>(`/admin/users/${id}`, b),
  materials: (status?: string) => get<AdminMaterialsReport>('/admin/materials' + qs({ status })),
  reindexMaterial: (id: string) => post<Material>(`/admin/materials/${id}/reindex`),
  deleteMaterial: (id: string) => request<void>(`/admin/materials/${id}`, { method: 'DELETE' }),
  setDefaultPageLimit: (default_page_limit: number) => put<{ default_page_limit: number }>('/admin/storage/settings', { default_page_limit }),
  tokens: (days = 30) => get<AdminTokenReport>('/admin/tokens' + qs({ days })),
  setDefaultLimit: (default_monthly_limit: number) => put<{ default_monthly_limit: number }>('/admin/tokens/settings', { default_monthly_limit }),
  attempts: (status?: string) => get<Attempt[]>('/admin/proctoring/attempts' + qs({ status })),
  attempt: (id: string) => get<{ attempt: Attempt; events: ProctorEvent[] }>(`/admin/proctoring/attempts/${id}`),
  warn: (id: string, message: string) => post<Attempt>(`/admin/proctoring/attempts/${id}/warn`, { message }),
  terminate: (id: string, reason: string) => post<Attempt>(`/admin/proctoring/attempts/${id}/terminate`, { reason }),
  review: (id: string, verdict: 'cleared' | 'confirmed', note?: string) => post<Attempt>(`/admin/proctoring/attempts/${id}/review`, { verdict, note }),
}

export const api = {
  register: (username: string, password: string) => post<Session>('/auth/register', { username, password }),
  login: (username: string, password: string) => post<Session>('/auth/login', { username, password }),
  saveProfile: (b: Record<string, unknown>) => post('/intake/profile', b),
  diagnostic: (goal: string, level: string) => post<DiagQ[]>('/intake/diagnostic', { goal, level }),
  submitDiagnostic: (user_id: string, goal: string, answers: { question_id: string; selected_option_index: number }[]) =>
    post<DiagResult>('/intake/diagnostic/submit', { user_id, goal, answers }),
  generateRoadmap: (user_id: string, preferences?: string, opts: { goal?: string; roadmap_id?: string } = {}) =>
    post<Roadmap>('/roadmap/generate', { user_id, preferences: preferences || undefined, ...opts }),
  tracks: (user_id: string) => get<Roadmap[]>('/roadmap/tracks' + qs({ user_id })),
  archiveTrack: (id: string, user_id: string) => request<void>(`/roadmap/${id}` + qs({ user_id }), { method: 'DELETE' }),
  discussRoadmap: (user_id: string, message: string, session_id: string, roadmap_id: string) =>
    post<DiscussReply>('/roadmap/discuss', { user_id, message, session_id, roadmap_id }),
  designTrack: (user_id: string, message: string, session_id: string) => post<DiscussReply>('/roadmap/design', { user_id, message, session_id }),
  /** With roadmap_id: revise that track. Without: create a new parallel track. */
  applyRoadmap: (user_id: string, proposal: Proposal, roadmap_id?: string) => post<Roadmap>('/roadmap/apply', { user_id, proposal, roadmap_id }),
  reopenChapter: (chapter_id: string) => post<ChapterComplete>(`/chapters/${chapter_id}/reopen`),
  roadmap: (user_id: string) => get<Roadmap>('/roadmap/current' + qs({ user_id })),
  chapter: (chapter_id: string) => get<ChapterDetail>(`/chapters/${chapter_id}`),
  completeChapter: (chapter_id: string) => post<ChapterComplete>(`/chapters/${chapter_id}/complete`),
  notes: (chapter_id: string) => get<Note>(`/chapters/${chapter_id}/notes`),
  guide: (chapter_id: string) => get<StudyGuide>(`/chapters/${chapter_id}/guide`),
  addResource: (chapter_id: string, b: { label: string; url: string; type?: string }) => post<ResourceLink>(`/chapters/${chapter_id}/resources`, b),
  deleteResource: (chapter_id: string, id: string) => request<void>(`/chapters/${chapter_id}/resources/${id}`, { method: 'DELETE' }),
  startSession: (user_id: string, energy_level: string) => post<SessionStart>('/session/start', { user_id, energy_level }),
  endSession: (b: Record<string, unknown>) => post<SessionEnd>('/session/end', b),
  chats: (user_id: string, kind: 'tutor' | 'roadmap' | 'design', chapter_id?: string) => get<ChatSummary[]>('/chats' + qs({ user_id, kind, chapter_id })),
  newChat: (user_id: string, kind: 'tutor' | 'roadmap' | 'design', chapter_id?: string) => post<ChatSummary>('/chats', { user_id, kind, chapter_id }),
  chat: (id: string, user_id: string) => get<ChatDetail>(`/chats/${id}` + qs({ user_id })),
  deleteChat: (id: string, user_id: string) => request<void>(`/chats/${id}` + qs({ user_id }), { method: 'DELETE' }),
  patchMessage: (id: string, user_id: string, meta: Record<string, unknown>) => request(`/chats/messages/${id}` + qs({ user_id }), { method: 'PATCH', body: JSON.stringify({ meta }) }),
  tutor: (b: Record<string, unknown>) => post<TutorReply>('/tutor/chat', b),
  brainMap: (user_id: string, roadmap_id?: string) => get<BrainMap>('/brain-map' + qs({ user_id, roadmap_id })),
  materials: () => get<Material[]>('/materials'),
  material: (id: string) => get<Material>(`/materials/${id}`),
  outline: (id: string) => get<{ material: Material; sections: Section[] }>(`/materials/${id}/outline`),
  storage: () => get<Storage>('/materials/storage'),
  upload: (file: File) => {
    const f = new FormData(); f.append('file', file)
    return request<Material>('/materials/upload', { method: 'POST', body: f })
  },
  deleteMaterial: (id: string) => request<void>(`/materials/${id}`, { method: 'DELETE' }),
  reindexMaterial: (id: string) => post<Material>(`/materials/${id}/reindex`),
  queryMaterials: (query: string) => post<RAGResult>('/materials/query', { query }),
  fromMaterials: (b: FromMaterialsBody) => post<CurriculumPreview>('/roadmap/from-materials', b),
  buildSchedule: () => post<Schedule>('/schedule/build', {}),
  schedule: (start?: string, end?: string) => get<Schedule>('/schedule' + qs({ start, end })),
  setTask: (id: string, status: 'pending' | 'done' | 'skipped') => patch<ScheduledTask>(`/schedule/tasks/${id}`, { status }),
  mistakes: (user_id: string) => get<Mistake[]>('/mistakes' + qs({ user_id, resolved: false })),
  resolveMistake: (id: string) => post(`/mistakes/${id}/resolve`),
  coach: (user_id: string) => get<Coach>('/coach/weekly-report' + qs({ user_id })),
  leaderboard: () => get<{ total_participants: number; rankings: LeaderEntry[] }>('/leaderboard'),
  me: () => get<{ id: string; username: string; role: 'student' | 'admin' }>('/auth/me'),
  myUsage: (days = 30) => get<MyUsage>('/usage/me' + qs({ days })),
  generateExam: (user_id: string, question_count: number, time_limit_minutes: number) =>
    post<Exam>('/exam/generate', { user_id, question_count, time_limit_minutes }),
  submitExam: (exam_id: string, user_id: string, answers: { question_id: string; selected_option_index: number }[]) =>
    post<ExamResult>('/exam/submit', { exam_id, user_id, answers, submitted_at: new Date().toISOString() }),
  proctor: (exam_id: string, events: { type: ProctorEventType; detail?: string }[]) => post<ProctorBeat>(`/exam/${exam_id}/proctor`, { events }),
  myAttempts: () => get<Attempt[]>('/exam/attempts'),
}
