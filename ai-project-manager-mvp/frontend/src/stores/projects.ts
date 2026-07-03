import { defineStore } from 'pinia'

import {
  createProject,
  deleteProject,
  getProjectSummary,
  listProjects,
  updateProject,
  updateProjectDashboard,
  type Project,
  type ProjectPayload,
  type ProjectSummary,
} from '@/api/projects'

export const emptyProject = (): ProjectPayload => ({
  name: '',
  customer: '',
  phase: '预投入',
  status: '配合销售、售前推进',
  contract_status: '未签合同',
  region: '',
  area: '',
  project_type: '政务大数据',
  progress: 0,
  days: '待定',
  tasks: 0,
  risks: 0,
  budget_usage: 0,
  new_demands: 0,
  health: 88,
  budget: '待定',
  incurred_cost: '',
  payment_2025: '0',
  manager: '陈晓勇',
  delivery: '',
  sales: '',
  start_date: '',
  pre_start_date: '',
  acceptance: '',
  end_date: '',
  spm: '',
  contract_no: '',
  background: '',
  plan: '',
  remark: '',
  dashboard: true,
  milestone_date: '',
  milestone_label: '',
})

export const useProjectStore = defineStore('projects', {
  state: () => ({
    projects: [] as Project[],
    summary: null as ProjectSummary | null,
    loading: false,
    error: '',
    selectedKey: '',
  }),
  getters: {
    dashboardProjects: (state) => state.projects.filter((project) => project.dashboard),
    selectedProject: (state) =>
      state.projects.find((project) => project.key === state.selectedKey) ||
      state.projects.find((project) => project.dashboard) ||
      state.projects[0],
  },
  actions: {
    async refresh(search = '') {
      this.loading = true
      this.error = ''
      try {
        const [projects, summary] = await Promise.all([listProjects({ search }), getProjectSummary()])
        this.projects = projects
        this.summary = summary
        if (!this.selectedKey || !projects.some((project) => project.key === this.selectedKey)) {
          this.selectedKey = projects.find((project) => project.dashboard)?.key || projects[0]?.key || ''
        }
      } catch (err) {
        this.error = err instanceof Error ? err.message : '项目数据加载失败'
      } finally {
        this.loading = false
      }
    },
    selectProject(key: string) {
      this.selectedKey = key
    },
    async saveProject(payload: ProjectPayload, key?: string) {
      if (key) {
        await updateProject(key, payload)
      } else {
        await createProject(payload)
      }
      await this.refresh()
    },
    async toggleDashboard(project: Project) {
      await updateProjectDashboard(project.key, !project.dashboard)
      await this.refresh()
    },
    async removeProject(key: string) {
      await deleteProject(key)
      await this.refresh()
    },
  },
})
