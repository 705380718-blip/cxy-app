import { defineStore } from 'pinia'

import {
  createTask,
  deleteDemand,
  deleteMilestone,
  deleteTask,
  getRiskSummary,
  getTaskCalendar,
  listDemands,
  listMilestones,
  listRisks,
  listTasks,
  updateDemand,
  updateMilestone,
  updateRisk,
  updateTask,
  type Demand,
  type Milestone,
  type MilestonePayload,
  type Risk,
  type RiskSummary,
  type Task,
  type TaskPayload,
  type TaskStatus,
} from '@/api/assets'

export interface PendingTaskDraft {
  task: TaskPayload
  demandId?: number
  advice?: string
}

export const emptyTask = (projectKey = ''): TaskPayload => ({
  project_key: projectKey,
  status: 'todo',
  title: '',
  description: '',
  owner: '待分配',
  start_date: '',
  due_date: '',
  progress: 0,
  source_extraction_id: null,
  demand_id: null,
})

function todayDateString() {
  const today = new Date()
  const year = today.getFullYear()
  const month = String(today.getMonth() + 1).padStart(2, '0')
  const day = String(today.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function currentMonthString() {
  return todayDateString().slice(0, 7)
}

export const useAssetStore = defineStore('assets', {
  state: () => ({
    tasks: [] as Task[],
    risks: [] as Risk[],
    demands: [] as Demand[],
    milestones: [] as Milestone[],
    riskSummary: null as RiskSummary | null,
    loading: false,
    error: '',
    projectKey: '',
    month: currentMonthString(),
    pendingTaskDraft: null as PendingTaskDraft | null,
  }),
  getters: {
    tasksByStatus: (state) => (status: TaskStatus) =>
      state.tasks.filter((task) => task.status === status),
    overdueTasks: (state) =>
      state.tasks.filter((task) => task.status !== 'done' && task.due_date && task.due_date < new Date().toISOString().slice(0, 10)),
    calendarItems: (state) => {
      const taskItems = state.tasks
        .filter((task) => task.due_date)
        .map((task) => ({
          id: `task-${task.id}`,
          date: task.due_date,
          title: task.title,
          type: 'task',
          status: task.status,
        }))
      const milestoneItems = state.milestones
        .filter((milestone) => milestone.date)
        .map((milestone) => ({
          id: `milestone-${milestone.id}`,
          date: milestone.date,
          title: milestone.title,
          type: 'milestone',
          status: milestone.status,
        }))
      return [...taskItems, ...milestoneItems]
    },
  },
  actions: {
    async refresh(projectKey?: string) {
      const resolvedProjectKey = projectKey ?? this.projectKey
      this.loading = true
      this.error = ''
      this.projectKey = resolvedProjectKey
      try {
        const [{ milestones }, tasks, risks, demands, riskSummary] = await Promise.all([
          getTaskCalendar({ project_key: resolvedProjectKey, month: this.month }),
          listTasks({ project_key: resolvedProjectKey }),
          listRisks({ project_key: resolvedProjectKey }),
          listDemands({ project_key: resolvedProjectKey }),
          getRiskSummary({ project_key: resolvedProjectKey }),
        ])
        this.tasks = tasks
        this.milestones = milestones
        this.risks = risks
        this.demands = demands
        this.riskSummary = riskSummary
      } catch (err) {
        this.error = err instanceof Error ? err.message : '任务与风险数据加载失败'
      } finally {
        this.loading = false
      }
    },
    async refreshAllTasks(projectKey?: string) {
      const resolvedProjectKey = projectKey ?? this.projectKey
      this.loading = true
      this.error = ''
      this.projectKey = resolvedProjectKey
      try {
        const [tasks, risks, demands, milestones, riskSummary] = await Promise.all([
          listTasks({ project_key: resolvedProjectKey }),
          listRisks({ project_key: resolvedProjectKey }),
          listDemands({ project_key: resolvedProjectKey }),
          listMilestones({ project_key: resolvedProjectKey }),
          getRiskSummary({ project_key: resolvedProjectKey }),
        ])
        this.tasks = tasks
        this.risks = risks
        this.demands = demands
        this.milestones = milestones
        this.riskSummary = riskSummary
      } catch (err) {
        this.error = err instanceof Error ? err.message : '任务与风险数据加载失败'
      } finally {
        this.loading = false
      }
    },
    async saveTask(task: TaskPayload) {
      const payload = {
        ...task,
        start_date: task.status === 'doing' && !task.start_date ? todayDateString() : task.start_date,
      }
      await createTask(payload)
      await this.refresh(this.projectKey)
    },
    prepareTaskDraft(draft: PendingTaskDraft) {
      this.pendingTaskDraft = draft
    },
    consumeTaskDraft() {
      const draft = this.pendingTaskDraft
      this.pendingTaskDraft = null
      return draft
    },
    async moveTask(task: Task, status: TaskStatus) {
      const payload: Partial<TaskPayload> = { status }
      if (status === 'doing' && !task.start_date) {
        payload.start_date = todayDateString()
      }
      await updateTask(task.id, payload)
      await this.refresh(this.projectKey)
    },
    async patchTask(task: Task, payload: Partial<TaskPayload>) {
      await updateTask(task.id, payload)
      await this.refresh(this.projectKey)
    },
    async removeTask(task: Task) {
      await deleteTask(task.id)
      await this.refresh(this.projectKey)
    },
    async patchRisk(risk: Risk, payload: Partial<Risk>) {
      await updateRisk(risk.id, payload)
      await this.refresh(this.projectKey)
    },
    async patchDemand(demand: Demand, payload: Partial<Demand>) {
      await updateDemand(demand.id, payload)
      await this.refresh(this.projectKey)
    },
    async patchMilestone(milestone: Milestone, payload: Partial<MilestonePayload>) {
      await updateMilestone(milestone.id, payload)
      await this.refreshAllTasks(this.projectKey)
    },
    async removeMilestone(milestone: Milestone) {
      await deleteMilestone(milestone.id)
      await this.refreshAllTasks(this.projectKey)
    },
    async removeDemand(demand: Demand) {
      await deleteDemand(demand.id)
      await this.refresh(this.projectKey)
    },
  },
})
