export type ExtractionType = 'task' | 'risk' | 'demand' | 'milestone'
export type ExtractionStatus = 'pending' | 'confirmed' | 'dismissed'

export interface Snippet {
  id: number
  project_key: string
  source_type: string
  raw_text: string
  extract_status: string
  created_at: string
}

export interface SnippetPayload {
  project_key: string
  source_type: string
  raw_text: string
}

export interface Extraction {
  id: number
  snippet_id: number
  project_key: string
  item_type: ExtractionType
  title: string
  description: string
  owner: string
  due_date: string
  probability: string
  impact: string
  response: string
  status: ExtractionStatus
  target_table: string
  target_record_id?: number | null
  created_at: string
}

export type ExtractionPayload = Partial<
  Pick<Extraction, 'item_type' | 'title' | 'description' | 'owner' | 'due_date' | 'probability' | 'impact' | 'response' | 'status'>
>

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

export function listSnippets(params: { project_key?: string } = {}) {
  return request<Snippet[]>(withQuery('/api/snippets', params))
}

export function createSnippet(snippet: SnippetPayload) {
  return request<Snippet>('/api/snippets', {
    method: 'POST',
    body: JSON.stringify(snippet),
  })
}

export function extractSnippet(id: number) {
  return request<{ snippet_id: number; items: Extraction[] }>(`/api/snippets/${id}/extract`, {
    method: 'POST',
  })
}

export function listExtractions(params: { project_key?: string; status?: string } = {}) {
  return request<Extraction[]>(withQuery('/api/extractions', params))
}

export function updateExtraction(id: number, extraction: ExtractionPayload) {
  return request<Extraction>(`/api/extractions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(extraction),
  })
}

export function confirmExtraction(id: number) {
  return request<Extraction>(`/api/extractions/${id}/confirm`, {
    method: 'POST',
  })
}
