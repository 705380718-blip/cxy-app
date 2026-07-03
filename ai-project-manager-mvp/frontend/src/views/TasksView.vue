<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Calendar, Delete, FolderAdd, List, Tickets } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { emptyTask, useAssetStore } from '@/stores/assets'
import { useProjectStore } from '@/stores/projects'
import type { Milestone, Task, TaskPayload, TaskStatus } from '@/api/assets'

const assetStore = useAssetStore()
const projectStore = useProjectStore()
const activeTab = ref('board')
const taskDialogVisible = ref(false)
const taskDetailVisible = ref(false)
const milestoneDetailVisible = ref(false)
const savingTaskDetail = ref(false)
const savingMilestoneStatus = ref(false)
const taskPage = ref(1)
const pageSize = 10
const boardKeyword = ref('')
const boardDueFilter = ref('')
const form = reactive<TaskPayload>(emptyTask())
const detailForm = reactive<TaskPayload>(emptyTask())
const selectedTask = ref<Task | null>(null)
const selectedMilestone = ref<Milestone | null>(null)
const milestoneStatus = ref('待开始')
const taskDraftAdvice = ref('')
const taskDraftDemandId = ref<number | null>(null)

const currentProjectKey = computed(() => projectStore.selectedProject?.key || '')
const statusLabel: Record<TaskStatus, string> = {
  confirm: '待确认',
  todo: '待办',
  doing: '进行中',
  done: '已完成',
}
const statusColumns: { key: TaskStatus; label: string; hint: string }[] = [
  { key: 'confirm', label: '待确认', hint: 'AI 提取后人工确认' },
  { key: 'todo', label: '待办', hint: '已确认待执行' },
  { key: 'doing', label: '进行中', hint: '正在推进' },
  { key: 'done', label: '已完成', hint: '已闭环归档' },
]
const milestoneStatusOptions = ['待开始', '已开始', '已完成', '已延期']

function formatDate(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const todayDate = computed(() => formatDate(new Date()))
const calendarMonth = computed(() => assetStore.month || todayDate.value.slice(0, 7))
const calendarMonthTitle = computed(() => {
  const [year, month] = calendarMonth.value.split('-')
  return `${year} 年 ${Number(month)} 月任务日历`
})
const calendarMonthModel = computed({
  get: () => calendarMonth.value,
  set: (month: string) => {
    if (month) void changeCalendarMonth(month)
  },
})

const createTaskDialogTitle = computed(() =>
  taskDraftDemandId.value ? '新建任务 · 需求评估' : '新建任务',
)

const taskMetrics = computed(() => [
  ['待确认', assetStore.tasksByStatus('confirm').length, '需要人工判断'],
  ['进行中', assetStore.tasksByStatus('doing').length, '影响本周推进'],
  ['逾期未完', assetStore.overdueTasks.length, `按 ${todayDate.value} 口径`],
  ['平均进度', `${assetStore.riskSummary?.avg_task_progress ?? 0}%`, '来自任务数据'],
])

const filteredBoardTasks = computed(() => {
  const keyword = boardKeyword.value.trim().toLowerCase()
  return assetStore.tasks.filter((task) => {
    const matchesKeyword = !keyword
      || task.title.toLowerCase().includes(keyword)
      || task.description.toLowerCase().includes(keyword)
      || task.owner.toLowerCase().includes(keyword)
    return matchesKeyword && matchesDueFilter(task)
  })
})

const ganttTasks = computed(() =>
  assetStore.tasks.filter((task) => task.due_date).slice(0, 8),
)

const pagedTasks = computed(() => {
  const start = (taskPage.value - 1) * pageSize
  return assetStore.tasks.slice(start, start + pageSize)
})

const calendarDays = computed(() => {
  const days = []
  const [year, month] = calendarMonth.value.split('-').map(Number)
  const daysInMonth = new Date(year, month, 0).getDate()
  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = `${calendarMonth.value}-${String(day).padStart(2, '0')}`
    days.push({
      day,
      date,
      items: assetStore.calendarItems.filter((item) => item.date === date),
    })
  }
  return days
})

function matchesDueFilter(task: Task) {
  if (!boardDueFilter.value) return true
  if (boardDueFilter.value === 'no_due') return !task.due_date
  if (!task.due_date) return false

  const today = todayDate.value
  if (boardDueFilter.value === 'overdue') return task.status !== 'done' && task.due_date < today
  if (boardDueFilter.value === 'today') return task.due_date === today
  if (boardDueFilter.value === 'week') {
    const dueDate = new Date(`${task.due_date}T00:00:00`)
    const todayTime = new Date(`${today}T00:00:00`)
    const days = Math.floor((dueDate.getTime() - todayTime.getTime()) / 86400000)
    return days >= 0 && days <= 7
  }
  return true
}

function sortBoardTasks(tasks: Task[]) {
  return [...tasks].sort((first, second) => {
    if (first.due_date && second.due_date && first.due_date !== second.due_date) {
      return first.due_date.localeCompare(second.due_date)
    }
    if (first.due_date && !second.due_date) return -1
    if (!first.due_date && second.due_date) return 1
    return second.id - first.id
  })
}

function boardTasksByStatus(status: TaskStatus) {
  return sortBoardTasks(filteredBoardTasks.value.filter((task) => task.status === status))
}

function resetBoardFilters() {
  boardKeyword.value = ''
  boardDueFilter.value = ''
}

watch(currentProjectKey, (key) => {
  taskPage.value = 1
  if (key) assetStore.refresh(key)
})

watch(activeTab, () => {
  taskPage.value = 1
})

onMounted(async () => {
  if (currentProjectKey.value) await assetStore.refresh(currentProjectKey.value)
  openPendingTaskDraft()
})

function openCreateTask() {
  Object.assign(form, emptyTask(currentProjectKey.value))
  taskDraftAdvice.value = ''
  taskDraftDemandId.value = null
  taskDialogVisible.value = true
}

function openPendingTaskDraft() {
  const draft = assetStore.consumeTaskDraft()
  if (!draft) return

  Object.assign(form, draft.task)
  taskDraftAdvice.value = draft.advice || ''
  taskDraftDemandId.value = draft.demandId ?? null
  taskDialogVisible.value = true
}

function taskPayload(task: Task): TaskPayload {
  return {
    project_key: task.project_key,
    status: task.status,
    title: task.title,
    description: task.description,
    owner: task.owner,
    start_date: task.start_date,
    due_date: task.due_date,
    progress: task.progress,
    source_extraction_id: task.source_extraction_id ?? null,
    demand_id: task.demand_id ?? null,
  }
}

function openTaskDetail(task: Task) {
  selectedTask.value = task
  Object.assign(detailForm, taskPayload(task))
  taskDetailVisible.value = true
}

function openMilestoneDetail(milestone: Milestone) {
  selectedMilestone.value = milestone
  milestoneStatus.value = milestone.status || '待开始'
  milestoneDetailVisible.value = true
}

function openCalendarItem(item: { id: string; type: string }) {
  if (item.type === 'task') {
    const task = assetStore.tasks.find((entry) => `task-${entry.id}` === item.id)
    if (task) openTaskDetail(task)
    return
  }

  const milestone = assetStore.milestones.find((entry) => `milestone-${entry.id}` === item.id)
  if (milestone) openMilestoneDetail(milestone)
}

async function changeCalendarMonth(month: string) {
  if (assetStore.month === month) return
  assetStore.month = month
  if (currentProjectKey.value) {
    await assetStore.refresh(currentProjectKey.value)
  }
}

async function saveTask() {
  if (!form.title.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }
  if (!form.project_key) {
    ElMessage.warning('请选择所属项目')
    return
  }
  await assetStore.saveTask({ ...form })
  if (taskDraftDemandId.value) {
    const demand = assetStore.demands.find((item) => item.id === taskDraftDemandId.value)
    if (demand) {
      await assetStore.patchDemand(demand, { status: '评估中' })
    }
  }
  await projectStore.refresh()
  taskDialogVisible.value = false
  taskDraftAdvice.value = ''
  taskDraftDemandId.value = null
  ElMessage.success('任务已新增')
}

async function saveTaskDetail() {
  if (!selectedTask.value) return
  if (!detailForm.title.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }

  savingTaskDetail.value = true
  try {
    await assetStore.patchTask(selectedTask.value, {
      ...detailForm,
      progress: Number(detailForm.progress),
    })
    await projectStore.refresh()
    selectedTask.value = assetStore.tasks.find((task) => task.id === selectedTask.value?.id) ?? selectedTask.value
    ElMessage.success('任务详情已更新')
  } finally {
    savingTaskDetail.value = false
  }
}

async function moveTask(task: Task, status: TaskStatus) {
  await assetStore.moveTask(task, status)
  await projectStore.refresh()
  if (selectedTask.value?.id === task.id) {
    selectedTask.value = assetStore.tasks.find((entry) => entry.id === task.id) ?? selectedTask.value
    Object.assign(detailForm, taskPayload(selectedTask.value))
  }
}

async function removeTask(task: Task) {
  try {
    await ElMessageBox.confirm(`确定删除任务“${task.title}”吗？删除后看板、列表、甘特和日历都会同步移除。`, '删除任务', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
    await assetStore.removeTask(task)
    await projectStore.refresh()
    if (selectedTask.value?.id === task.id) {
      taskDetailVisible.value = false
      selectedTask.value = null
    }
    ElMessage.success('任务已删除')
  } catch (err) {
    if (err !== 'cancel' && err !== 'close') {
      ElMessage.error(err instanceof Error ? `删除失败：${err.message}` : '删除失败')
    }
  }
}

async function saveMilestoneStatus() {
  if (!selectedMilestone.value) return

  savingMilestoneStatus.value = true
  try {
    await assetStore.patchMilestone(selectedMilestone.value, { status: milestoneStatus.value })
    await projectStore.refresh()
    selectedMilestone.value = assetStore.milestones.find((entry) => entry.id === selectedMilestone.value?.id) ?? selectedMilestone.value
    ElMessage.success('里程碑状态已更新')
  } finally {
    savingMilestoneStatus.value = false
  }
}
</script>

<template>
  <section class="module-toolbar">
    <el-select v-model="projectStore.selectedKey" placeholder="选择项目" class="project-select">
      <el-option
        v-for="project in projectStore.projects"
        :key="project.key"
        :label="project.name"
        :value="project.key"
      />
    </el-select>
    <el-segmented v-model="activeTab" :options="[
      { label: '看板', value: 'board' },
      { label: '列表', value: 'list' },
      { label: '甘特', value: 'gantt' },
      { label: '日历', value: 'calendar' },
    ]" />
    <el-button type="primary" :icon="FolderAdd" @click="openCreateTask">新建任务</el-button>
  </section>

  <section class="task-metrics">
    <div v-for="metric in taskMetrics" :key="metric[0]" class="compact-metric">
      <span>{{ metric[0] }}</span>
      <strong>{{ metric[1] }}</strong>
      <small>{{ metric[2] }}</small>
    </div>
  </section>

  <section v-if="activeTab === 'board'" class="board-controls">
    <el-input v-model="boardKeyword" clearable placeholder="搜索任务、说明、负责人" />
    <el-select v-model="boardDueFilter" clearable placeholder="截止时间">
      <el-option label="已逾期" value="overdue" />
      <el-option label="今天截止" value="today" />
      <el-option label="7 天内截止" value="week" />
      <el-option label="无截止日期" value="no_due" />
    </el-select>
    <el-button @click="resetBoardFilters">重置</el-button>
  </section>

  <section v-if="activeTab === 'board'" class="task-board">
    <div v-for="column in statusColumns" :key="column.key" class="task-column">
      <div class="task-column-head">
        <div>
          <strong>{{ column.label }}</strong>
          <small>{{ column.hint }}</small>
        </div>
        <el-tag>{{ boardTasksByStatus(column.key).length }} / {{ assetStore.tasksByStatus(column.key).length }}</el-tag>
      </div>
      <div class="task-column-body">
        <article
          v-for="task in boardTasksByStatus(column.key)"
          :key="task.id"
          class="task-card task-detail-trigger"
          @click="openTaskDetail(task)"
        >
          <div class="task-title-row">
            <strong>{{ task.title }}</strong>
            <div class="task-card-tools">
              <el-tag size="small" :type="task.status === 'done' ? 'success' : task.status === 'doing' ? 'primary' : 'warning'">
                {{ column.label }}
              </el-tag>
              <el-button
                class="task-delete-button"
                :icon="Delete"
                size="small"
                text
                type="danger"
                title="删除任务"
                @click.stop="removeTask(task)"
              />
            </div>
          </div>
          <p>{{ task.description || '暂无说明' }}</p>
          <div class="task-card-meta">
            <span>{{ task.owner || '待分配' }}</span>
            <span>{{ task.due_date || '无截止日期' }}</span>
          </div>
          <el-progress :percentage="task.progress" :stroke-width="7" />
          <div class="task-actions">
            <el-button size="small" :disabled="task.status === 'todo'" @click.stop="moveTask(task, 'todo')">待办</el-button>
            <el-button size="small" :disabled="task.status === 'doing'" @click.stop="moveTask(task, 'doing')">推进</el-button>
            <el-button size="small" type="success" :disabled="task.status === 'done'" @click.stop="moveTask(task, 'done')">完成</el-button>
          </div>
        </article>
        <el-empty v-if="boardTasksByStatus(column.key).length === 0" description="暂无匹配任务" :image-size="72" />
      </div>
    </div>
  </section>

  <section v-else-if="activeTab === 'list'" class="panel">
    <div class="panel-head">
      <h3><el-icon><List /></el-icon> 任务列表</h3>
      <el-tag>{{ assetStore.tasks.length }} 条</el-tag>
    </div>
    <el-table
      v-loading="assetStore.loading"
      :data="pagedTasks"
      class="task-detail-table"
      @row-click="openTaskDetail"
    >
      <el-table-column prop="title" label="任务" min-width="260">
        <template #default="{ row }">
          <strong>{{ row.title }}</strong>
          <p class="table-sub">{{ row.description || '暂无说明' }}</p>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column prop="owner" label="负责人" width="120" />
      <el-table-column prop="due_date" label="截止日期" width="130" />
      <el-table-column label="进度" width="180">
        <template #default="{ row }">
          <el-progress :percentage="row.progress" :stroke-width="8" />
        </template>
      </el-table-column>
    </el-table>
    <div class="table-pagination">
      <el-pagination
        v-model:current-page="taskPage"
        :page-size="pageSize"
        layout="prev, pager, next, total"
        :total="assetStore.tasks.length"
      />
    </div>
  </section>

  <section v-else-if="activeTab === 'gantt'" class="panel">
    <div class="panel-head">
      <h3><el-icon><Tickets /></el-icon> 轻量甘特</h3>
      <span class="panel-note">按关键任务截止日期排序</span>
    </div>
    <div class="gantt-list">
      <div
        v-for="(task, index) in ganttTasks"
        :key="task.id"
        class="gantt-row task-detail-trigger"
        @click="openTaskDetail(task)"
      >
        <span>{{ task.title }}</span>
        <div class="gantt-track">
          <i :style="{ left: `${Math.min(index * 9, 64)}%`, width: `${Math.max(16, task.progress / 2)}%` }" />
        </div>
        <strong>{{ task.due_date }}</strong>
      </div>
    </div>
  </section>

  <section v-else class="panel">
    <div class="panel-head">
      <h3><el-icon><Calendar /></el-icon> {{ calendarMonthTitle }}</h3>
      <div class="calendar-head-actions">
        <el-date-picker
          v-model="calendarMonthModel"
          type="month"
          value-format="YYYY-MM"
          format="YYYY 年 MM 月"
          placeholder="选择月份"
          class="calendar-month-picker"
        />
        <span class="panel-note">任务和里程碑共用同一项目筛选</span>
      </div>
    </div>
    <div class="calendar-grid">
      <div v-for="day in calendarDays" :key="day.date" class="calendar-cell" :class="{ today: day.date === todayDate }">
        <strong>{{ day.day }}</strong>
        <div class="calendar-items">
          <span
            v-for="item in day.items"
            :key="item.id"
            :class="['calendar-pill', item.type]"
            @click="openCalendarItem(item)"
          >
            {{ item.title }}
          </span>
        </div>
      </div>
    </div>
  </section>

  <el-dialog v-model="taskDialogVisible" :title="createTaskDialogTitle" width="680px">
    <el-form label-position="top" class="task-form">
      <div v-if="taskDraftAdvice" class="ai-assessment-advice field-full">
        <strong>AI 评估建议</strong>
        <p>{{ taskDraftAdvice }}</p>
      </div>
      <el-form-item label="任务名称" class="field-full"><el-input v-model="form.title" /></el-form-item>
      <el-form-item label="所属项目">
        <el-select v-model="form.project_key">
          <el-option
            v-for="project in projectStore.projects"
            :key="project.key"
            :label="project.name"
            :value="project.key"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="form.status">
          <el-option label="待确认" value="confirm" />
          <el-option label="待办" value="todo" />
          <el-option label="进行中" value="doing" />
          <el-option label="已完成" value="done" />
        </el-select>
      </el-form-item>
      <el-form-item label="负责人"><el-input v-model="form.owner" /></el-form-item>
      <el-form-item label="开始日期"><el-date-picker v-model="form.start_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="截止日期"><el-date-picker v-model="form.due_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="完成进度" class="field-full">
        <el-slider v-model="form.progress" :min="0" :max="100" :step="5" show-input />
      </el-form-item>
      <el-form-item label="说明" class="field-full"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="taskDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="saveTask">保存任务</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="taskDetailVisible" :title="selectedTask ? `任务详情 · ${selectedTask.title}` : '任务详情'" width="760px">
    <el-form v-if="selectedTask" label-position="top" class="task-form task-detail-form">
      <el-form-item label="任务名称" class="field-full"><el-input v-model="detailForm.title" /></el-form-item>
      <el-form-item label="状态">
        <el-select v-model="detailForm.status">
          <el-option label="待确认" value="confirm" />
          <el-option label="待办" value="todo" />
          <el-option label="进行中" value="doing" />
          <el-option label="已完成" value="done" />
        </el-select>
      </el-form-item>
      <el-form-item label="负责人"><el-input v-model="detailForm.owner" /></el-form-item>
      <el-form-item label="开始日期"><el-date-picker v-model="detailForm.start_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="截止日期"><el-date-picker v-model="detailForm.due_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="完成进度" class="field-full">
        <el-slider v-model="detailForm.progress" :min="0" :max="100" :step="5" show-input />
      </el-form-item>
      <el-form-item label="详细说明" class="field-full">
        <el-input v-model="detailForm.description" type="textarea" :rows="4" />
      </el-form-item>
      <div class="task-detail-summary field-full">
        <span>当前状态：{{ statusLabel[detailForm.status] }}</span>
        <span>任务 ID：{{ selectedTask.id }}</span>
        <span>来源：{{ selectedTask.source_extraction_id ? `归集事项 #${selectedTask.source_extraction_id}` : '手动维护' }}</span>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="taskDetailVisible = false">关闭</el-button>
      <el-button type="primary" :loading="savingTaskDetail" @click="saveTaskDetail">保存修改</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="milestoneDetailVisible" :title="selectedMilestone ? `里程碑详情 · ${selectedMilestone.title}` : '里程碑详情'" width="560px">
    <div v-if="selectedMilestone" class="milestone-detail">
      <strong>{{ selectedMilestone.title }}</strong>
      <p>日期：{{ selectedMilestone.date || '未设置' }}</p>
      <el-form label-position="top">
        <el-form-item label="状态">
          <el-select v-model="milestoneStatus">
            <el-option
              v-for="status in milestoneStatusOptions"
              :key="status"
              :label="status"
              :value="status"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <p>来源：{{ selectedMilestone.source_extraction_id ? `归集事项 #${selectedMilestone.source_extraction_id}` : '项目计划' }}</p>
    </div>
    <template #footer>
      <el-button @click="milestoneDetailVisible = false">关闭</el-button>
      <el-button type="primary" :loading="savingMilestoneStatus" @click="saveMilestoneStatus">保存状态</el-button>
    </template>
  </el-dialog>
</template>
