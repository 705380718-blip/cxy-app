async function requestBlob(url: string, options?: RequestInit): Promise<Blob> {
  const response = await fetch(url, options)
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`)
  }
  return response.blob()
}

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`)
  }
  return response.json()
}

export async function downloadSystemData() {
  const blob = await requestBlob('/api/system/export')
  downloadBlob(blob, `ai-project-manager-system-data-${timestamp()}.zip`)
}

export async function downloadSystemBackup(backupUrl: string, filename?: string) {
  const blob = await requestBlob(backupUrl)
  downloadBlob(blob, filename || `ai-project-manager-backup-${timestamp()}.zip`)
}

function timestamp() {
  return new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function clearSystemData() {
  return requestJson<{ status: string; backup_path: string; backup_name: string; backup_url: string }>('/api/system/clear', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}
