export type TaskStatus = 'confirm' | 'todo' | 'doing' | 'done'

export interface Task {
  id: number
  project_key: string
  status: TaskStatus
  title: string
  description: string
  owner: string
  start_date: string
  due_date: string
  progress: number
  source_extraction_id?: number | null
  demand_id?: number | null
}

export type TaskPayload = Omit<Task, 'id'>

export interface Risk {
  id: number
  project_key: string
  title: string
  description: string
  probability: string
  impact: '低' | '中' | '高' | string
  status: string
  response: string
  source_extraction_id?: number | null
}

export interface Demand {
  id: number
  project_key: string
  title: string
  description: string
  status: string
  scope_impact: string
  source_extraction_id?: number | null
  source_item_type?: string
  source_title?: string
  source_type?: string
  source_text?: string
  source_created_at?: string
}

export interface Milestone {
  id: number
  project_key: string
  title: string
  date: string
  status: string
  source_extraction_id?: number | null
}

export type MilestonePayload = Omit<Milestone, 'id'>

export interface CalendarPayload {
  tasks: Task[]
  milestones: Milestone[]
}

export interface RiskSummary {
  total: number
  high_count: number
  open_count: number
  demand_count: number
  avg_task_progress: number
  health: number
  overdue_tasks: number
  due_soon_tasks: number
  overdue_milestones: number
  due_soon_milestones: number
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`)
  }
  return response.json()
}

function withQuery(path: string, params: Record<string, string | undefined>) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value)
  })
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return `${path}${suffix}`
}

export function listTasks(params: { project_key?: string; status?: string } = {}) {
  return request<Task[]>(withQuery('/api/tasks', params))
}

export function createTask(task: TaskPayload) {
  return request<Task>('/api/tasks', {
    method: 'POST',
    body: JSON.stringify(task),
  })
}

export function updateTask(id: number, task: Partial<TaskPayload>) {
  return request<Task>(`/api/tasks/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(task),
  })
}

export function deleteTask(id: number) {
  return request<{ status: string; id: number }>(`/api/tasks/${id}`, {
    method: 'DELETE',
  })
}

export function getTaskCalendar(params: { project_key?: string; month?: string } = {}) {
  return request<CalendarPayload>(withQuery('/api/tasks/calendar', params))
}

export function listRisks(params: { project_key?: string } = {}) {
  return request<Risk[]>(withQuery('/api/risks', params))
}

export function updateRisk(id: number, risk: Partial<Risk>) {
  return request<Risk>(`/api/risks/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(risk),
  })
}

export function getRiskSummary(params: { project_key?: string } = {}) {
  return request<RiskSummary>(withQuery('/api/risks/summary', params))
}

export function listDemands(params: { project_key?: string } = {}) {
  return request<Demand[]>(withQuery('/api/demands', params))
}

export function updateDemand(id: number, demand: Partial<Demand>) {
  return request<Demand>(`/api/demands/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(demand),
  })
}

export function deleteDemand(id: number) {
  return request<{ status: string; id: number }>(`/api/demands/${id}`, {
    method: 'DELETE',
  })
}

export function listMilestones(params: { project_key?: string } = {}) {
  return request<Milestone[]>(withQuery('/api/milestones', params))
}

export function updateMilestone(id: number, milestone: Partial<MilestonePayload>) {
  return request<Milestone>(`/api/milestones/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(milestone),
  })
}

export function deleteMilestone(id: number) {
  return request<{ status: string; id: number }>(`/api/milestones/${id}`, {
    method: 'DELETE',
  })
}
