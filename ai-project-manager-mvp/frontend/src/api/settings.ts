export interface ModelOverride {
  capability: string
  label: string
  mode: 'inherit' | 'custom'
  provider: string
  model: string
  base_url: string
}

export interface ModelConfig {
  provider: string
  provider_label: string
  model: string
  base_url: string
  api_key: string
  verify_ssl: boolean
  temperature: number
  status: 'untested' | 'connected' | 'failed'
  status_message: string
  last_tested_at: string
  has_api_key: boolean
  overrides: ModelOverride[]
}

export interface AgentProfile {
  name: string
  role: string
  tone: string
  responsibilities: string[]
  forbidden: string[]
  default_output_format: string
  long_term_preferences: string[]
  proactive_reminders: string[]
  memory_policy: string
}

export interface ModelTestResult {
  status: ModelConfig['status']
  status_message: string
  last_tested_at: string
  config: ModelConfig
}

export interface AssistantResponse {
  answer: string
  project_key: string
  view: string
  source: string
  action_type: string
  action_payload: Record<string, unknown>
  agent_name?: string
}

export interface AssistantMessage {
  id: number
  project_key: string
  view: string
  role: 'user' | 'assistant'
  content: string
  action_type: string
  action_payload: Record<string, unknown>
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

export function getModelConfig() {
  return request<ModelConfig>('/api/settings/model-config')
}

export function saveModelConfig(config: ModelConfig) {
  return request<ModelConfig>('/api/settings/model-config', {
    method: 'PUT',
    body: JSON.stringify(config),
  })
}

export function testModelConfig(config: ModelConfig) {
  return request<ModelTestResult>('/api/settings/model-config/test', {
    method: 'POST',
    body: JSON.stringify(config),
  })
}

export function getAgentProfile() {
  return request<AgentProfile>('/api/settings/agent-profile')
}

export function saveAgentProfile(profile: AgentProfile) {
  return request<AgentProfile>('/api/settings/agent-profile', {
    method: 'PUT',
    body: JSON.stringify(profile),
  })
}

export function askAssistant(payload: { project_key: string; view: string; message: string }) {
  return request<AssistantResponse>('/api/assistant/chat', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listAssistantMessages(projectKey: string, limit = 20) {
  const query = new URLSearchParams({ project_key: projectKey, limit: String(limit) })
  return request<AssistantMessage[]>(`/api/assistant/messages?${query.toString()}`)
}
