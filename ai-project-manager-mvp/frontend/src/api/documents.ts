export interface DocumentTemplate {
  id: number
  name: string
  template_type: string
  original_filename: string
  file_path: string
  status: string
  variables: string
  created_at: string
  updated_at: string
}

export interface DocumentVersion {
  id: number
  project_key: string
  template_id: number
  title: string
  content_markdown: string
  content_html: string
  version: number
  word_status: string
  pdf_status: string
  lark_status: string
  export_path: string
  export_url: string
  created_at: string
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

async function formRequest<T>(url: string, body: FormData): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    body,
  })
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`)
  }
  return response.json()
}

function withQuery(path: string, params: Record<string, string | number | undefined>) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value))
  })
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return `${path}${suffix}`
}

export function listDocumentTemplates() {
  return request<DocumentTemplate[]>('/api/document-templates')
}

export function uploadDocumentTemplate(payload: { name: string; template_type: string; file: File }) {
  const body = new FormData()
  body.set('name', payload.name)
  body.set('template_type', payload.template_type)
  body.set('file', payload.file)
  return formRequest<DocumentTemplate>('/api/document-templates/upload', body)
}

export function deleteDocumentTemplate(templateId: number) {
  return request<{ deleted: boolean; template_id: number; removed_files: number }>(`/api/document-templates/${templateId}`, {
    method: 'DELETE',
  })
}

export function extractDocumentContent(file: File) {
  const body = new FormData()
  body.set('file', file)
  return formRequest<{ filename: string; content: string }>('/api/document-content/extract', body)
}

export function listDocumentVersions(params: { project_key?: string; template_id?: number } = {}) {
  return request<DocumentVersion[]>(withQuery('/api/document-versions', params))
}

export function generateDocumentVersion(payload: {
  project_key: string
  template_id: number
  title?: string
  input_content?: string
}) {
  return request<DocumentVersion>('/api/document-versions/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function exportDocumentWord(versionId: number) {
  return request<DocumentVersion>(`/api/document-versions/${versionId}/export-word`, {
    method: 'POST',
  })
}
