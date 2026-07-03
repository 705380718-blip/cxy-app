import { defineStore } from 'pinia'

import {
  confirmExtraction,
  createSnippet,
  extractSnippet,
  listExtractions,
  updateExtraction,
  type Extraction,
  type ExtractionPayload,
} from '@/api/inbox'

export const useInboxStore = defineStore('inbox', {
  state: () => ({
    extractions: [] as Extraction[],
    loading: false,
    extracting: false,
    error: '',
    projectKey: '',
  }),
  getters: {
    pendingCount: (state) => state.extractions.filter((item) => item.status === 'pending').length,
    typeCount: (state) => (type: string) =>
      state.extractions.filter((item) => item.item_type === type && item.status === 'pending').length,
  },
  actions: {
    async refresh(projectKey?: string) {
      const resolvedProjectKey = projectKey ?? this.projectKey
      this.loading = true
      this.error = ''
      this.projectKey = resolvedProjectKey
      try {
        this.extractions = await listExtractions({ project_key: resolvedProjectKey, status: 'pending' })
      } catch (err) {
        this.error = err instanceof Error ? err.message : '信息归集数据加载失败'
      } finally {
        this.loading = false
      }
    },
    async submitAndExtract(payload: { project_key: string; source_type: string; raw_text: string }) {
      this.extracting = true
      this.error = ''
      try {
        const snippet = await createSnippet(payload)
        await extractSnippet(snippet.id)
        await this.refresh(payload.project_key)
      } catch (err) {
        this.error = err instanceof Error ? err.message : 'AI 提取失败'
      } finally {
        this.extracting = false
      }
    },
    async saveExtraction(extraction: Extraction, payload: ExtractionPayload) {
      await updateExtraction(extraction.id, payload)
      await this.refresh(this.projectKey)
    },
    async confirm(extraction: Extraction) {
      await confirmExtraction(extraction.id)
      await this.refresh(this.projectKey)
    },
    async dismiss(extraction: Extraction) {
      await updateExtraction(extraction.id, { status: 'dismissed' })
      await this.refresh(this.projectKey)
    },
  },
})
