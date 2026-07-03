import { defineStore } from 'pinia'

import {
  getAgentProfile,
  getModelConfig,
  saveAgentProfile,
  saveModelConfig,
  testModelConfig,
  type AgentProfile,
  type ModelConfig,
} from '@/api/settings'

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    config: null as ModelConfig | null,
    agentProfile: null as AgentProfile | null,
    loading: false,
    testing: false,
    saving: false,
    savingAgent: false,
    error: '',
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const [config, agentProfile] = await Promise.all([getModelConfig(), getAgentProfile()])
        this.config = config
        this.agentProfile = agentProfile
      } catch (err) {
        this.error = err instanceof Error ? err.message : '模型与智能体配置加载失败'
      } finally {
        this.loading = false
      }
    },
    async save() {
      if (!this.config) return
      this.saving = true
      this.error = ''
      try {
        this.config = await saveModelConfig(this.config)
      } catch (err) {
        this.error = err instanceof Error ? err.message : '模型配置保存失败'
      } finally {
        this.saving = false
      }
    },
    async test() {
      if (!this.config) return
      this.testing = true
      this.error = ''
      try {
        const result = await testModelConfig(this.config)
        this.config = result.config
      } catch (err) {
        this.error = err instanceof Error ? err.message : '模型连通性测试失败'
      } finally {
        this.testing = false
      }
    },
    async saveAgent() {
      if (!this.agentProfile) return
      this.savingAgent = true
      this.error = ''
      try {
        this.agentProfile = await saveAgentProfile(this.agentProfile)
      } catch (err) {
        this.error = err instanceof Error ? err.message : '智能体配置保存失败'
      } finally {
        this.savingAgent = false
      }
    },
  },
})
