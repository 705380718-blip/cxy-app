export interface ProjectHealthBreakdown {
  health: number
  penalties: {
    risk: number
    schedule: number
    budget: number
    milestone: number
    demand: number
    total: number
  }
  signals: {
    open_risks: number
    high_risks: number
    overdue_tasks: number
    due_soon_tasks: number
    overdue_milestones: number
    due_soon_milestones: number
    open_demands: number
  }
}

export interface Project {
  key: string
  name: string
  customer: string
  phase: string
  status: string
  contract_status: string
  region: string
  area: string
  project_type: string
  progress: number
  days: string
  tasks: number
  risks: number
  budget_usage: number
  new_demands: number
  health: number
  budget: string
  incurred_cost: string
  payment_2025: string
  manager: string
  delivery: string
  sales: string
  start_date: string
  pre_start_date: string
  acceptance: string
  end_date: string
  spm: string
  contract_no: string
  background: string
  plan: string
  remark: string
  dashboard: boolean
  milestone_date: string
  milestone_label: string
  health_breakdown?: ProjectHealthBreakdown
}

export interface ProjectSummary {
  total: number
  dashboard_count: number
  avg_progress: number
  task_count: number
  risk_count: number
  avg_health: number
}

export type ProjectPayload = Omit<Project, 'key'> & { key?: string }

export interface ProjectGanttPayload {
  project_key: string
  rows: unknown[]
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

export function listProjects(params: { search?: string; dashboard?: boolean } = {}) {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  if (typeof params.dashboard === 'boolean') query.set('dashboard', String(params.dashboard))
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return request<Project[]>(`/api/projects${suffix}`)
}

export function getProjectSummary() {
  return request<ProjectSummary>('/api/projects/summary')
}

export function createProject(project: ProjectPayload) {
  return request<Project>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(project),
  })
}

export function updateProject(key: string, project: ProjectPayload) {
  return request<Project>(`/api/projects/${key}`, {
    method: 'PUT',
    body: JSON.stringify(project),
  })
}

export function updateProjectDashboard(key: string, dashboard: boolean) {
  return request<Project>(`/api/projects/${key}/dashboard`, {
    method: 'PATCH',
    body: JSON.stringify({ dashboard }),
  })
}

export function getProjectGantt(key: string) {
  return request<ProjectGanttPayload>(`/api/projects/${key}/gantt`)
}

export function saveProjectGantt(key: string, rows: unknown[]) {
  return request<ProjectGanttPayload>(`/api/projects/${key}/gantt`, {
    method: 'PUT',
    body: JSON.stringify({ rows }),
  })
}

export function deleteProject(key: string) {
  return request<{ status: string; key: string }>(`/api/projects/${key}`, {
    method: 'DELETE',
  })
}
