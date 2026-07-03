import { defineStore } from 'pinia'

import {
  deleteDocumentTemplate,
  exportDocumentWord,
  generateDocumentVersion,
  listDocumentTemplates,
  listDocumentVersions,
  uploadDocumentTemplate,
  type DocumentTemplate,
  type DocumentVersion,
} from '@/api/documents'

export const useDocumentStore = defineStore('documents', {
  state: () => ({
    templates: [] as DocumentTemplate[],
    versions: [] as DocumentVersion[],
    selectedTemplateId: 0,
    selectedVersionId: 0,
    loading: false,
    generating: false,
    exporting: false,
    error: '',
  }),
  getters: {
    selectedTemplate: (state) =>
      state.templates.find((template) => template.id === state.selectedTemplateId) || state.templates[0],
    selectedVersion: (state) =>
      state.versions.find((version) => version.id === state.selectedVersionId) || state.versions[0],
  },
  actions: {
    async refresh(projectKey = '') {
      this.loading = true
      this.error = ''
      try {
        const templates = await listDocumentTemplates()
        this.templates = templates
        if (!templates.some((template) => template.id === this.selectedTemplateId)) {
          this.selectedTemplateId = templates[0]?.id || 0
        }
        const versions = await listDocumentVersions({
          project_key: projectKey,
          template_id: this.selectedTemplateId || undefined,
        })
        this.versions = versions
        if (!versions.some((version) => version.id === this.selectedVersionId)) {
          this.selectedVersionId = versions[0]?.id || 0
        }
      } catch (err) {
        this.error = err instanceof Error ? err.message : '文档数据加载失败'
      } finally {
        this.loading = false
      }
    },
    async uploadTemplate(payload: { name: string; template_type: string; file: File }, projectKey = '') {
      const template = await uploadDocumentTemplate(payload)
      this.selectedTemplateId = template.id
      await this.refresh(projectKey)
    },
    async deleteTemplate(templateId: number, projectKey = '') {
      await deleteDocumentTemplate(templateId)
      if (this.selectedTemplateId === templateId) {
        this.selectedTemplateId = 0
        this.selectedVersionId = 0
      }
      await this.refresh(projectKey)
    },
    async generate(projectKey: string, title?: string, inputContent = '') {
      if (!this.selectedTemplateId) throw new Error('请先选择模板')
      this.generating = true
      try {
        const version = await generateDocumentVersion({
          project_key: projectKey,
          template_id: this.selectedTemplateId,
          title,
          input_content: inputContent,
        })
        this.selectedVersionId = version.id
        await this.refresh(projectKey)
      } finally {
        this.generating = false
      }
    },
    async exportWord(projectKey: string, versionId?: number) {
      const targetVersionId = versionId || this.selectedVersion?.id
      if (!targetVersionId) throw new Error('请先生成文档版本')
      this.exporting = true
      try {
        const version = await exportDocumentWord(targetVersionId)
        this.selectedVersionId = version.id
        await this.refresh(projectKey)
      } finally {
        this.exporting = false
      }
    },
  },
})
