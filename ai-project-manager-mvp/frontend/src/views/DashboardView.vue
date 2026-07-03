<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Calendar, Delete, TrendCharts, Warning } from '@element-plus/icons-vue'

import type { Project } from '@/api/projects'
import { getProjectGantt, saveProjectGantt } from '@/api/projects'
import type { Milestone } from '@/api/assets'
import { useAssetStore } from '@/stores/assets'
import { useProjectStore } from '@/stores/projects'

const store = useProjectStore()
const assetStore = useAssetStore()

type GanttBar = {
  start?: number
  end?: number
  startDate?: string
  endDate?: string
  text: string
  status?: GanttBarStatus
  owner?: string
  note?: string
}

type GanttBarStatus = 'planned' | 'active' | 'done'

type GanttRow = {
  label: string
  bars: GanttBar[]
}

type GanttScale = 'month' | 'week'

type GanttPeriod = {
  key: string
  label: string
  dateRange: string
  start: Date
  end: Date
}

type GanttEditForm = {
  text: string
  startDate: string
  endDate: string
  status: GanttBarStatus
  owner: string
  note: string
}

const GANTT_STORAGE_KEY = 'ai-pm-dashboard-gantt-v1'
const GANTT_SCALE_STORAGE_KEY = 'ai-pm-dashboard-gantt-scale-v1'
const DAY_MS = 24 * 60 * 60 * 1000

function loadStoredGanttRows(): Record<string, GanttRow[]> {
  if (typeof window === 'undefined') return {}
  try {
    const payload = JSON.parse(window.localStorage.getItem(GANTT_STORAGE_KEY) || '{}')
    if (!payload || typeof payload !== 'object') return {}
    return payload
  } catch {
    return {}
  }
}

function saveStoredGanttRows(rowsByProject: Record<string, GanttRow[]>) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(GANTT_STORAGE_KEY, JSON.stringify(rowsByProject))
}

function isGanttRow(value: unknown): value is GanttRow {
  if (!value || typeof value !== 'object') return false
  const row = value as { label?: unknown; bars?: unknown }
  return typeof row.label === 'string' && Array.isArray(row.bars)
}

function normalizeGanttRows(rows: unknown[]): GanttRow[] {
  return rows.filter(isGanttRow).map((row) => ({
    label: row.label,
    bars: row.bars
      .filter((bar): bar is GanttBar => Boolean(bar) && typeof bar === 'object' && typeof (bar as GanttBar).text === 'string')
      .map((bar) => ({ ...bar })),
  }))
}

function loadStoredGanttScale(): GanttScale {
  if (typeof window === 'undefined') return 'month'
  return window.localStorage.getItem(GANTT_SCALE_STORAGE_KEY) === 'week' ? 'week' : 'month'
}

function saveStoredGanttScale(scale: GanttScale) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(GANTT_SCALE_STORAGE_KEY, scale)
}

const selected = computed(() => store.selectedProject)
const ganttRowsByProject = ref<Record<string, GanttRow[]>>(loadStoredGanttRows())
const displayGanttRows = computed(() => (selected.value ? ganttRowsByProject.value[selected.value.key] || [] : []))
const ganttTitle = computed(() => `${selected.value?.name || '暂无项目'}实施进度表`)
const ganttScale = ref<GanttScale>(loadStoredGanttScale())
const detailVisible = ref(false)
const detailProject = ref<Project | null>(null)
const detailMetric = ref('')
const milestoneDetailVisible = ref(false)
const selectedMilestone = ref<Milestone | null>(null)
const milestoneStatus = ref('待开始')
const savingMilestoneStatus = ref(false)
const importDialogVisible = ref(false)
const planInput = ref('')
const planFileInput = ref<HTMLInputElement | null>(null)
const ganttEditVisible = ref(false)
const editingGanttTarget = ref<{ rowIndex: number; barIndex: number } | null>(null)
const ganttEditForm = ref<GanttEditForm>({
  text: '',
  startDate: '',
  endDate: '',
  status: 'planned',
  owner: '',
  note: '',
})
const ganttStatusOptions: { label: string; value: GanttBarStatus }[] = [
  { label: '计划阶段', value: 'planned' },
  { label: '进行中', value: 'active' },
  { label: '已按时完成', value: 'done' },
]
const ganttStatusLabel: Record<GanttBarStatus, string> = {
  planned: '计划阶段',
  active: '进行中',
  done: '已按时完成',
}
const milestoneStatusOptions = ['待开始', '已开始', '已完成', '已延期']
const statusLabel: Record<string, string> = {
  confirm: '待确认',
  todo: '待办',
  doing: '进行中',
  done: '已完成',
}
const metrics = computed(() => [
  ['项目总数', store.summary?.total ?? 0, `${store.summary?.dashboard_count ?? 0} 个展示中`],
  ['平均进度', `${store.summary?.avg_progress ?? 0}%`, '全部项目'],
  ['任务总数', store.summary?.task_count ?? 0, '来自项目摘要'],
  ['开放风险', store.summary?.risk_count ?? 0, '需持续跟进'],
  ['健康分', store.summary?.avg_health ?? 0, '平均值'],
])

function healthExplanationLines(project: Project | null) {
  const breakdown = project?.health_breakdown
  if (!project || !breakdown) {
    return ['暂无健康分拆解数据，请刷新项目后再查看。']
  }
  const penalties = breakdown.penalties
  const signals = breakdown.signals
  return [
    `计算公式：100 - ${penalties.total} = ${breakdown.health} 分`,
    `风险扣 ${penalties.risk} 分：开放风险 ${signals.open_risks} 项，高影响 ${signals.high_risks} 项。`,
    `任务排期扣 ${penalties.schedule} 分：逾期任务 ${signals.overdue_tasks} 项，7 天内到期 ${signals.due_soon_tasks} 项。`,
    `里程碑扣 ${penalties.milestone} 分：逾期里程碑 ${signals.overdue_milestones} 项，14 天内到期 ${signals.due_soon_milestones} 项。`,
    `预算扣 ${penalties.budget} 分：预算使用率 ${project.budget_usage || 0}%。`,
    `需求扣 ${penalties.demand} 分：开放需求 ${signals.open_demands} 项。`,
  ]
}

const ganttPeriods = computed(() => buildGanttPeriods(displayGanttRows.value, ganttScale.value))
const ganttTimelineStyle = computed(() => ({
  '--gantt-axis-width': `${Math.max(860, ganttPeriods.value.length * (ganttScale.value === 'week' ? 118 : 170))}px`,
}))
const todayOffset = computed(() => getTodayOffsetPercent(ganttPeriods.value))
const showTodayLine = computed(() => todayOffset.value !== null)
const todayLineStyle = computed(() => ({
  left: `${todayOffset.value ?? 0}%`,
}))
const ganttAxisTicks = computed(() => buildAxisTicks(ganttPeriods.value, ganttScale.value))
const loadedGanttProjectKeys = new Set<string>()

async function persistGanttRows(projectKey: string, rows: GanttRow[]) {
  await saveProjectGantt(projectKey, rows)
  ganttRowsByProject.value = {
    ...ganttRowsByProject.value,
    [projectKey]: rows,
  }
  saveStoredGanttRows(ganttRowsByProject.value)
  loadedGanttProjectKeys.add(projectKey)
}

async function loadGanttForProject(projectKey: string) {
  if (!projectKey || loadedGanttProjectKeys.has(projectKey)) return
  try {
    const payload = await getProjectGantt(projectKey)
    const serverRows = normalizeGanttRows(payload.rows)
    const localRows = loadStoredGanttRows()[projectKey] || []
    if (!serverRows.length && localRows.length) {
      await persistGanttRows(projectKey, localRows)
      return
    }
    ganttRowsByProject.value = {
      ...ganttRowsByProject.value,
      [projectKey]: serverRows,
    }
    saveStoredGanttRows(ganttRowsByProject.value)
    loadedGanttProjectKeys.add(projectKey)
  } catch (err) {
    const localRows = loadStoredGanttRows()[projectKey] || []
    if (localRows.length) {
      ganttRowsByProject.value = {
        ...ganttRowsByProject.value,
        [projectKey]: localRows,
      }
      loadedGanttProjectKeys.add(projectKey)
    }
    ElMessage.warning(err instanceof Error ? `甘特图数据加载失败：${err.message}` : '甘特图数据加载失败')
  }
}

async function openProjectDetail(project: Project, metric: string) {
  store.selectProject(project.key)
  detailProject.value = project
  detailMetric.value = metric
  detailVisible.value = true
  await assetStore.refreshAllTasks(project.key)
}

function openMilestoneDetail(milestone: Milestone) {
  selectedMilestone.value = milestone
  milestoneStatus.value = milestone.status || '待开始'
  milestoneDetailVisible.value = true
}

async function saveMilestoneStatus() {
  if (!selectedMilestone.value) return

  savingMilestoneStatus.value = true
  try {
    await assetStore.patchMilestone(selectedMilestone.value, { status: milestoneStatus.value })
    await store.refresh()
    selectedMilestone.value = assetStore.milestones.find((entry) => entry.id === selectedMilestone.value?.id) ?? selectedMilestone.value
    if (detailProject.value) {
      detailProject.value = store.projects.find((project) => project.key === detailProject.value?.key) ?? detailProject.value
    }
    ElMessage.success('里程碑状态已更新')
  } finally {
    savingMilestoneStatus.value = false
  }
}

async function removeMilestone(milestone: Milestone) {
  try {
    await ElMessageBox.confirm(`确定删除里程碑“${milestone.title}”吗？删除后首页项目卡片和日历都会同步移除。`, '删除里程碑', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
    await assetStore.removeMilestone(milestone)
    await store.refresh()
    if (selectedMilestone.value?.id === milestone.id) {
      milestoneDetailVisible.value = false
      selectedMilestone.value = null
    }
    if (detailProject.value) {
      detailProject.value = store.projects.find((project) => project.key === detailProject.value?.key) ?? detailProject.value
    }
    ElMessage.success('里程碑已删除')
  } catch (err) {
    if (err !== 'cancel' && err !== 'close') {
      ElMessage.error(err instanceof Error ? `里程碑删除失败：${err.message}` : '里程碑删除失败')
    }
  }
}

function openImportPlanDialog() {
  if (!selected.value) {
    ElMessage.warning('请先新建或选择项目，再导入计划表')
    return
  }
  importDialogVisible.value = true
  planInput.value = ''
}

function triggerPlanFileDialog() {
  planFileInput.value?.click()
}

async function pickPlanFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const isReadableText = file.type.startsWith('text/') || /\.(csv|txt|md|log)$/i.test(file.name)
  if (!isReadableText) {
    ElMessage.warning('当前支持 CSV、TXT、Markdown 等文本计划表')
    return
  }
  planInput.value = await file.text()
  ElMessage.success('计划表内容已读取')
}

function padDatePart(value: number) {
  return String(value).padStart(2, '0')
}

function toDateString(date: Date) {
  return `${date.getFullYear()}-${padDatePart(date.getMonth() + 1)}-${padDatePart(date.getDate())}`
}

function parseDateString(value: string, fallbackYear = new Date().getFullYear()) {
  const normalized = value
    .replace(/[年月]/g, '-')
    .replace(/[日号]/g, '')
    .replace(/[./]/g, '-')
    .replace(/\s+/g, '')
  const parts = normalized.split('-').filter(Boolean).map(Number)
  const [year, month, day] = parts.length >= 3 ? parts : [fallbackYear, parts[0], parts[1]]
  if (!year || !month || !day) return null
  const date = new Date(year, month - 1, day)
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null
  return date
}

function parseDateRange(value: string) {
  const normalized = value.replace(/[（()）]/g, ' ').replace(/\s+/g, ' ')
  const rangeMatch = normalized.match(/((?:\d{4}[-/.年月])?\d{1,2}[-/.月]\d{1,2}(?:日|号)?)\s*(?:到|至|--?|—|~|～)\s*((?:\d{4}[-/.年月])?\d{1,2}[-/.月]\d{1,2}(?:日|号)?)/)
  if (!rangeMatch) return null
  const start = parseDateString(rangeMatch[1])
  const end = parseDateString(rangeMatch[2], start?.getFullYear())
  if (!start || !end) return null
  return start <= end ? { startDate: toDateString(start), endDate: toDateString(end) } : { startDate: toDateString(end), endDate: toDateString(start) }
}

function toDate(value?: string) {
  return value ? parseDateString(value) : null
}

function stripMarkdownTableNoise(value: string) {
  return value
    .replace(/^[:\-|\s]+|[:\-|\s]+$/g, '')
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function splitPlanLine(line: string) {
  const trimmed = line.trim().replace(/^\||\|$/g, '')
  const delimiter = trimmed.includes('\t') ? /\t+/ : trimmed.includes('|') ? /\|/ : /,|，/
  return trimmed.split(delimiter).map(stripMarkdownTableNoise).filter(Boolean)
}

function isHeaderCells(cells: string[]) {
  const joined = cells.join('')
  return joined.includes('阶段') && joined.includes('时间') && joined.includes('工作重点')
}

function isMarkdownDivider(cells: string[]) {
  return cells.length > 0 && cells.every((cell) => /^:?-{2,}:?$/.test(cell))
}

function formatGanttTaskName(value: string) {
  return stripMarkdownTableNoise(value).replace(/^阶段\s*[一二三四五六七八九十\d]+[：:、.\-\s]*/, '') || '计划事项'
}

function getGanttBarTooltip(bar: GanttBar) {
  const lines = [formatGanttTaskName(bar.text)]
  lines.push(`状态：${ganttStatusLabel[getBarStatus(bar)]}`)
  const dates = [bar.startDate, bar.endDate].filter(Boolean).join(' 至 ')
  if (dates) lines.push(`时间：${dates}`)
  if (bar.owner) lines.push(`负责人：${bar.owner}`)
  if (bar.note) lines.push(`备注：${bar.note}`)
  return lines.join('\n')
}

function trimBarText(value: string) {
  return stripMarkdownTableNoise(value)
}

function addGanttRow(buckets: Map<string, GanttBar[]>, label: string, bar: GanttBar) {
  const cleanLabel = stripMarkdownTableNoise(label)
    .replace(/\s*第\s*\d+\s*[-–—]?\s*\d*\s*周.*$/, '')
    .trim()
  if (!cleanLabel || !bar.startDate || !bar.endDate) return
  const bars = buckets.get(cleanLabel) || []
  if (!bars.some((item) => item.startDate === bar.startDate && item.endDate === bar.endDate && item.text === bar.text)) {
    bars.push(bar)
  }
  buckets.set(cleanLabel, bars)
}

function parseDelimitedPlanRows(text: string, buckets: Map<string, GanttBar[]>) {
  text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const cells = splitPlanLine(line)
      if (cells.length < 2 || isHeaderCells(cells) || isMarkdownDivider(cells)) return
      const dateCellIndex = cells.findIndex((cell) => parseDateRange(cell))
      const label = cells[0]
      if (dateCellIndex >= 0) {
        const range = parseDateRange(cells[dateCellIndex])
        if (!range) return
        const detailCells = cells.filter((_, index) => index !== 0 && index !== dateCellIndex)
        addGanttRow(buckets, label, {
          ...range,
          text: trimBarText(label || detailCells[0] || '计划阶段'),
        })
        return
      }
      const dateIndexes = cells
        .map((cell, index) => ({ index, date: parseDateString(cell) }))
        .filter((item): item is { index: number; date: Date } => Boolean(item.date))
      if (dateIndexes.length < 2) return
      const detailCells = cells.filter((_, index) => index !== 0 && !dateIndexes.some((item) => item.index === index))
      addGanttRow(buckets, label, {
        startDate: toDateString(dateIndexes[0].date),
        endDate: toDateString(dateIndexes[1].date),
        text: trimBarText(label || detailCells[0] || '计划阶段'),
      })
    })
}

function parseLoosePlanRows(text: string, buckets: Map<string, GanttBar[]>) {
  const pattern = /(阶段[一二三四五六七八九十\d]+[：:][^\n|,，]+?)(?=\s+第|\s*\n|$)[\s\S]{0,180}?((?:\d{4}[-/.年月])?\d{1,2}[-/.月]\d{1,2}(?:日|号)?\s*(?:到|至|--?|—|~|～)\s*(?:\d{4}[-/.年月])?\d{1,2}[-/.月]\d{1,2}(?:日|号)?)/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text))) {
    const range = parseDateRange(match[2])
    if (!range) continue
    addGanttRow(buckets, match[1], {
      ...range,
      text: trimBarText(match[1]),
    })
  }
}

function parseGanttPlan(text: string): GanttRow[] {
  const buckets = new Map<string, GanttBar[]>()
  parseDelimitedPlanRows(text, buckets)
  parseLoosePlanRows(text, buckets)

  return Array.from(buckets.entries()).map(([label, bars]) => ({
    label,
    bars: bars.sort((a, b) => (a.startDate || '').localeCompare(b.startDate || '')),
  }))
}

function startOfMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function endOfMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0)
}

function startOfWeek(date: Date) {
  const next = new Date(date)
  const day = next.getDay() || 7
  next.setDate(next.getDate() - day + 1)
  return next
}

function endOfWeek(date: Date) {
  const next = startOfWeek(date)
  next.setDate(next.getDate() + 6)
  return next
}

function formatShortDate(date: Date) {
  return `${date.getMonth() + 1}.${date.getDate()}`
}

function getPlanBounds(rows: GanttRow[]) {
  const dates = rows.flatMap((row) =>
    row.bars.flatMap((bar) => [toDate(bar.startDate), toDate(bar.endDate)]).filter((date): date is Date => Boolean(date)),
  )
  const now = new Date()
  dates.push(new Date(now.getFullYear(), now.getMonth(), now.getDate()))
  const timestamps = dates.map((date) => date.getTime())
  return {
    start: new Date(Math.min(...timestamps)),
    end: new Date(Math.max(...timestamps)),
  }
}

function buildGanttPeriods(rows: GanttRow[], scale: GanttScale): GanttPeriod[] {
  const bounds = getPlanBounds(rows)
  const start = scale === 'week' ? startOfWeek(bounds.start) : startOfMonth(bounds.start)
  const end = scale === 'week' ? endOfWeek(bounds.end) : endOfMonth(bounds.end)
  const periods: GanttPeriod[] = []
  const cursor = new Date(start)
  let index = 1

  while (cursor <= end) {
    const periodStart = new Date(cursor)
    const periodEnd = scale === 'week' ? endOfWeek(periodStart) : endOfMonth(periodStart)
    periods.push({
      key: `${scale}-${toDateString(periodStart)}`,
      label: scale === 'week' ? `第 ${index} 周` : `${periodStart.getFullYear()}年${periodStart.getMonth() + 1}月`,
      dateRange: `${formatShortDate(periodStart)} - ${formatShortDate(periodEnd)}`,
      start: periodStart,
      end: periodEnd,
    })
    cursor.setDate(cursor.getDate() + (scale === 'week' ? 7 : periodEnd.getDate()))
    index += 1
  }

  return periods
}

function getTimelineRange(periods: GanttPeriod[]) {
  if (!periods.length) return null
  return {
    start: periods[0].start,
    end: periods[periods.length - 1].end,
  }
}

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value))
}

function getDateOffsetPercent(date: Date, periods = ganttPeriods.value) {
  const range = getTimelineRange(periods)
  if (!range) return 0
  const totalDays = Math.max(1, Math.round((range.end.getTime() - range.start.getTime()) / DAY_MS) + 1)
  const offsetDays = Math.round((date.getTime() - range.start.getTime()) / DAY_MS)
  return clampPercent((offsetDays / totalDays) * 100)
}

function buildAxisTicks(periods: GanttPeriod[], scale: GanttScale) {
  return periods.map((period) => ({
    key: period.key,
    left: `${getDateOffsetPercent(period.start, periods)}%`,
    label: scale === 'week' ? formatSlashDate(period.start) : `${period.start.getFullYear()}-${padDatePart(period.start.getMonth() + 1)}`,
    subLabel: scale === 'week' ? '' : `${formatShortDate(period.start)} - ${formatShortDate(period.end)}`,
  }))
}

function formatSlashDate(date: Date) {
  return `${padDatePart(date.getMonth() + 1)}/${padDatePart(date.getDate())}`
}

function getBarTimelinePercent(bar: GanttBar, periods = ganttPeriods.value) {
  const range = getTimelineRange(periods)
  if (!range) return { left: 0, width: 0 }
  const totalDays = Math.max(1, Math.round((range.end.getTime() - range.start.getTime()) / DAY_MS) + 1)
  const startDate = toDate(bar.startDate)
  const endDate = toDate(bar.endDate)

  if (!startDate || !endDate) {
    const start = Math.max(1, Math.min(periods.length, bar.start || 1))
    const end = Math.max(start + 1, Math.min(periods.length + 1, bar.end || start + 1))
    return {
      left: ((start - 1) / periods.length) * 100,
      width: ((end - start) / periods.length) * 100,
    }
  }

  const leftDays = Math.round((startDate.getTime() - range.start.getTime()) / DAY_MS)
  const durationDays = Math.max(1, Math.round((endDate.getTime() - startDate.getTime()) / DAY_MS) + 1)
  const left = clampPercent((leftDays / totalDays) * 100)
  const width = Math.min(100 - left, (durationDays / totalDays) * 100)
  return {
    left,
    width: Math.max(0, width),
  }
}

function getBarTimelineStyle(bar: GanttBar) {
  const position = getBarTimelinePercent(bar)
  return {
    left: `${position.left}%`,
    width: `${Math.max(position.width, 2)}%`,
  }
}

function getBarStatus(bar: GanttBar) {
  if (bar.status) return bar.status
  const startDate = toDate(bar.startDate)
  const endDate = toDate(bar.endDate)
  if (!startDate || !endDate) return 'planned'
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (endDate < today) return 'done'
  if (startDate <= today && endDate >= today) return 'active'
  return 'planned'
}

function getTodayOffsetPercent(periods: GanttPeriod[]) {
  if (!periods.length) return null
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const range = getTimelineRange(periods)
  if (!range || today < range.start || today > range.end) return null
  return getDateOffsetPercent(today, periods)
}

function updateGanttScale(scale: GanttScale) {
  ganttScale.value = scale
  saveStoredGanttScale(scale)
}

function handleGanttScaleChange(value: string | number) {
  updateGanttScale(value === 'week' ? 'week' : 'month')
}

async function generateGanttFromPlan() {
  if (!selected.value) {
    ElMessage.warning('请先新建或选择项目，再生成甘特图')
    return
  }
  if (!planInput.value.trim()) {
    ElMessage.warning('请先粘贴或上传项目计划表内容')
    return
  }
  const parsedRows = parseGanttPlan(planInput.value)
  if (!parsedRows.length) {
    ElMessage.warning('没有解析到有效计划行，请检查计划表内容')
    return
  }
  try {
    await persistGanttRows(selected.value.key, parsedRows)
    importDialogVisible.value = false
    ElMessage.success('已根据计划表生成甘特图')
  } catch (err) {
    ElMessage.error(err instanceof Error ? `甘特图保存失败：${err.message}` : '甘特图保存失败')
  }
}

function openGanttBarEditor(rowIndex: number, barIndex: number) {
  const row = displayGanttRows.value[rowIndex]
  const bar = row?.bars[barIndex]
  if (!row || !bar) return
  editingGanttTarget.value = { rowIndex, barIndex }
  ganttEditForm.value = {
    text: formatGanttTaskName(bar.text || row.label),
    startDate: bar.startDate || '',
    endDate: bar.endDate || '',
    status: bar.status || getBarStatus(bar),
    owner: bar.owner || '',
    note: bar.note || '',
  }
  ganttEditVisible.value = true
}

async function saveGanttBarEdit() {
  if (!selected.value || !editingGanttTarget.value) return
  const name = ganttEditForm.value.text.trim()
  const startDate = parseDateString(ganttEditForm.value.startDate)
  const endDate = parseDateString(ganttEditForm.value.endDate, startDate?.getFullYear())
  if (!name) {
    ElMessage.warning('请填写任务名称')
    return
  }
  if (!startDate || !endDate) {
    ElMessage.warning('请填写有效的起止日期')
    return
  }
  if (startDate > endDate) {
    ElMessage.warning('开始日期不能晚于结束日期')
    return
  }

  const { rowIndex, barIndex } = editingGanttTarget.value
  const projectRows = displayGanttRows.value.map((row, index) => {
    if (index !== rowIndex) return row
    return {
      ...row,
      label: name,
      bars: row.bars.map((bar, currentBarIndex) =>
        currentBarIndex === barIndex
          ? {
              ...bar,
              text: name,
              startDate: toDateString(startDate),
              endDate: toDateString(endDate),
              status: ganttEditForm.value.status,
              owner: ganttEditForm.value.owner.trim(),
              note: ganttEditForm.value.note.trim(),
            }
          : bar,
      ),
    }
  })

  try {
    await persistGanttRows(selected.value.key, projectRows)
    ganttEditVisible.value = false
    editingGanttTarget.value = null
    ElMessage.success('任务进度条已更新')
  } catch (err) {
    ElMessage.error(err instanceof Error ? `甘特图保存失败：${err.message}` : '甘特图保存失败')
  }
}

async function resetGanttForSelectedProject() {
  if (!selected.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  if (!displayGanttRows.value.length && !planInput.value) {
    ElMessage.info('当前项目暂无甘特图数据')
    return
  }
  try {
    await ElMessageBox.confirm('确定清空当前项目的甘特图数据和导入内容吗？清空后可重新导入计划表生成。', '重置甘特图', {
      type: 'warning',
      confirmButtonText: '重置',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await persistGanttRows(selected.value.key, [])
    planInput.value = ''
    ElMessage.success('已重置当前项目甘特图')
  } catch (err) {
    ElMessage.error(err instanceof Error ? `甘特图重置失败：${err.message}` : '甘特图重置失败')
  }
}

function drawWrappedText(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, maxWidth: number, lineHeight: number, align: CanvasTextAlign = 'center') {
  ctx.textAlign = align
  const sourceLines = text.split('\n')
  const lines: string[] = []
  sourceLines.forEach((source) => {
    let line = ''
    Array.from(source).forEach((char) => {
      const trial = line + char
      if (ctx.measureText(trial).width > maxWidth && line) {
        lines.push(line)
        line = char
      } else {
        line = trial
      }
    })
    if (line) lines.push(line)
  })
  const startY = y - ((lines.length - 1) * lineHeight) / 2
  lines.forEach((line, index) => ctx.fillText(line, x, startY + index * lineHeight))
}

function exportGanttPng() {
  if (!displayGanttRows.value.length) {
    ElMessage.warning('请先导入项目计划表后再导出甘特图')
    return
  }
  const periods = ganttPeriods.value
  if (!periods.length) {
    ElMessage.warning('没有可导出的时间轴')
    return
  }
  const canvas = document.createElement('canvas')
  const left = 90
  const top = 120
  const labelWidth = 270
  const axisWidth = Math.max(920, periods.length * (ganttScale.value === 'week' ? 118 : 170))
  const headerHeight = 82
  const rowHeight = 76
  const chartWidth = labelWidth + axisWidth
  const rows = displayGanttRows.value
  const chartHeight = headerHeight + rowHeight * rows.length
  const width = Math.max(1400, left * 2 + chartWidth)
  const height = Math.max(720, top + chartHeight + 96)
  const ratio = window.devicePixelRatio || 1
  canvas.width = width * ratio
  canvas.height = height * ratio
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    ElMessage.error('当前浏览器无法生成 PNG')
    return
  }
  ctx.scale(ratio, ratio)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)

  ctx.fillStyle = '#142033'
  ctx.font = 'bold 30px system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(ganttTitle.value, width / 2, 72)

  ctx.strokeStyle = '#9fb8cf'
  ctx.setLineDash([6, 5])
  for (let row = 0; row <= rows.length + 1; row += 1) {
    const y = row === 0 ? top : top + headerHeight + (row - 1) * rowHeight
    ctx.beginPath()
    ctx.moveTo(left, y)
    ctx.lineTo(left + chartWidth, y)
    ctx.stroke()
  }
  ctx.setLineDash([])
  const ticks = buildAxisTicks(periods, ganttScale.value)
  ticks.forEach((tick) => {
    const x = left + labelWidth + (Number.parseFloat(tick.left) / 100) * axisWidth
    ctx.beginPath()
    ctx.moveTo(x, top)
    ctx.lineTo(x, top + chartHeight)
    ctx.stroke()
  })

  ctx.fillStyle = '#243149'
  ctx.font = 'bold 16px system-ui, sans-serif'
  ticks.forEach((tick) => {
    const x = left + labelWidth + (Number.parseFloat(tick.left) / 100) * axisWidth
    drawWrappedText(ctx, tick.subLabel ? `${tick.label}\n${tick.subLabel}` : tick.label, x, top + headerHeight / 2, 92, 20)
  })

  ctx.font = 'bold 18px system-ui, sans-serif'
  rows.forEach((row, rowIndex) => {
    const rowTop = top + headerHeight + rowIndex * rowHeight
    drawWrappedText(ctx, formatGanttTaskName(row.label), left + labelWidth / 2, rowTop + rowHeight / 2, labelWidth - 26, 24)
    row.bars.forEach((bar) => {
      const position = getBarTimelinePercent(bar, periods)
      const x = left + labelWidth + (position.left / 100) * axisWidth
      const y = rowTop + 22
      const barWidth = Math.max(28, (position.width / 100) * axisWidth)
      const status = getBarStatus(bar)
      ctx.fillStyle = status === 'done' ? '#9ed9c7' : status === 'active' ? '#ffd24c' : '#b8d8ff'
      ctx.fillRect(x, y, barWidth, 32)
      ctx.fillStyle = '#142033'
      ctx.font = 'bold 15px system-ui, sans-serif'
      drawWrappedText(ctx, formatGanttTaskName(bar.text), x + barWidth / 2, y + 19, barWidth - 18, 18)
    })
  })

  if (todayOffset.value !== null) {
    const todayX = left + labelWidth + axisWidth * (todayOffset.value / 100)
    ctx.strokeStyle = '#e84b42'
    ctx.setLineDash([6, 6])
    ctx.beginPath()
    ctx.moveTo(todayX, top + 18)
    ctx.lineTo(todayX, top + chartHeight + 36)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.strokeStyle = '#e84b42'
    ctx.strokeRect(todayX - 28, top + 18, 56, 46)
    ctx.fillStyle = '#d94a43'
    ctx.font = 'bold 22px system-ui, sans-serif'
    ctx.fillText('今日', todayX, top + 50)
  }

  ctx.fillStyle = '#9ed9c7'
  ctx.fillRect(width - 340, height - 64, 42, 12)
  ctx.fillStyle = '#6d7890'
  ctx.font = '18px system-ui, sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText('已按时完成', width - 288, height - 52)
  ctx.fillStyle = '#d94a43'
  ctx.fillText('红色虚线为今日位置', width - 178, height - 52)

  canvas.toBlob((blob) => {
    if (!blob) {
      ElMessage.error('PNG 生成失败')
      return
    }
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selected.value?.name || '暂无项目'}-实施进度表.png`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('PNG 已导出，可上传或复制到飞书')
  }, 'image/png')
}

onMounted(() => {
  if (selected.value?.key) {
    loadGanttForProject(selected.value.key)
  }
})

watch(
  () => selected.value?.key,
  (projectKey) => {
    if (projectKey) {
      loadGanttForProject(projectKey)
    }
  },
)
</script>

<template>
  <section class="metric-grid">
    <div v-for="metric in metrics" :key="metric[0]" class="metric-card">
      <span>{{ metric[0] }}</span>
      <strong>{{ metric[1] }}</strong>
      <small>{{ metric[2] }}</small>
    </div>
  </section>

  <section class="panel dashboard-panel">
      <div class="panel-head">
        <h3>项目驾驶舱</h3>
        <el-tag type="success">{{ store.dashboardProjects.length }} 个项目</el-tag>
      </div>
      <div class="project-strip">
        <article
          v-for="project in store.dashboardProjects"
          :key="project.key"
          class="project-card"
          :class="{ active: selected?.key === project.key }"
          :data-testid="`project-card-${project.key}`"
          role="button"
          tabindex="0"
          @click="store.selectProject(project.key)"
          @keyup.enter="store.selectProject(project.key)"
        >
          <div class="project-card-head">
            <strong>{{ project.name }}</strong>
            <el-tag size="small">{{ project.phase }}</el-tag>
          </div>
          <p>{{ project.customer }} · {{ project.region }}</p>
          <div class="project-progress">
            <span>进度 {{ project.progress }}%</span>
            <el-progress :percentage="project.progress" :stroke-width="8" :show-text="false" />
          </div>
          <div class="project-meta">
            <button type="button" :data-testid="`project-${project.key}-tasks`" @click.stop="openProjectDetail(project, '任务')">任务 {{ project.tasks }}</button>
            <button type="button" :data-testid="`project-${project.key}-risks`" @click.stop="openProjectDetail(project, '风险')">风险 {{ project.risks }}</button>
            <button type="button" :data-testid="`project-${project.key}-health`" @click.stop="openProjectDetail(project, '健康')">健康 {{ project.health }}</button>
          </div>
        </article>
      </div>
  </section>

  <section class="panel dashboard-gantt-panel">
    <div class="panel-head">
      <h3>项目实施进度表</h3>
      <div class="gantt-actions">
        <el-segmented
          :model-value="ganttScale"
          :options="[
            { label: '月', value: 'month' },
            { label: '周', value: 'week' },
          ]"
          data-testid="gantt-scale-toggle"
          @update:model-value="handleGanttScaleChange"
        />
        <el-button type="primary" data-testid="import-plan-button" @click="openImportPlanDialog">导入计划表生成</el-button>
        <el-button data-testid="reset-gantt-button" @click="resetGanttForSelectedProject">重置</el-button>
        <el-button data-testid="export-gantt-png-button" @click="exportGanttPng">导出 PNG</el-button>
      </div>
    </div>
    <div class="dashboard-gantt">
      <h3>{{ ganttTitle }}</h3>
      <div class="dashboard-gantt-chart" :style="ganttTimelineStyle">
        <div class="dashboard-gantt-corner" />
        <div class="dashboard-gantt-axis">
          <div
            v-for="tick in ganttAxisTicks"
            :key="tick.key"
            class="dashboard-gantt-axis-tick"
            :style="{ left: tick.left }"
          >
            <span>{{ tick.label }}</span>
            <small v-if="tick.subLabel">{{ tick.subLabel }}</small>
          </div>
          <div v-if="showTodayLine" class="dashboard-gantt-today" :style="todayLineStyle">
            <span>今日</span>
          </div>
        </div>
        <template v-for="(row, rowIndex) in displayGanttRows" :key="row.label">
          <el-tooltip :content="formatGanttTaskName(row.label)" placement="top" popper-class="gantt-tooltip">
            <div class="dashboard-gantt-label">
              <span v-for="line in formatGanttTaskName(row.label).split('\n')" :key="line">{{ line }}</span>
            </div>
          </el-tooltip>
          <div class="dashboard-gantt-track">
            <div
              v-for="tick in ganttAxisTicks"
              :key="`line-${row.label}-${tick.key}`"
              class="dashboard-gantt-gridline"
              :style="{ left: tick.left }"
            />
            <div v-if="showTodayLine" class="dashboard-gantt-today-line" :style="todayLineStyle" />
            <el-tooltip
              v-for="(bar, barIndex) in row.bars"
              :key="`${bar.text}-${bar.startDate || bar.start}-${bar.endDate || bar.end}`"
              :content="getGanttBarTooltip(bar)"
              placement="top"
              popper-class="gantt-tooltip"
            >
              <div
                class="dashboard-gantt-bar"
                :class="`is-${getBarStatus(bar)}`"
                :style="getBarTimelineStyle(bar)"
                role="button"
                tabindex="0"
                @click="openGanttBarEditor(rowIndex, barIndex)"
                @keyup.enter="openGanttBarEditor(rowIndex, barIndex)"
              >
                <span v-for="line in formatGanttTaskName(bar.text).split('\n')" :key="line">{{ line }}</span>
              </div>
            </el-tooltip>
          </div>
        </template>
        <div v-if="displayGanttRows.length === 0" class="dashboard-gantt-empty">
          {{ selected ? '尚未导入项目计划表，导入后将按计划内容生成工作行和阶段条。' : '暂无项目，创建项目后可导入计划表生成实施进度。' }}
        </div>
      </div>
      <div class="dashboard-gantt-legend">
        <span><i class="is-done" />已按时完成</span>
        <span><i class="is-active" />进行中</span>
        <span><i class="is-planned" />计划阶段</span>
        <strong>红色虚线为今日位置</strong>
      </div>
    </div>
  </section>

  <el-dialog v-model="importDialogVisible" title="导入计划表生成甘特图" width="760px">
    <div class="gantt-import-dialog">
      <p>粘贴 Excel/飞书表格内容、CSV，或上传文本计划表。系统会按里程碑任务、起止时间和事项内容自动生成甘特图。</p>
      <input ref="planFileInput" class="file-input-hidden" type="file" accept=".csv,.txt,.md,.log" @change="pickPlanFile" />
      <el-button data-testid="upload-plan-file-button" @click="triggerPlanFileDialog">上传计划表文件</el-button>
      <el-input
        v-model="planInput"
        type="textarea"
        data-testid="gantt-plan-input"
        :rows="9"
        placeholder="阶段/工作内容,开始时间,结束时间,事项内容&#10;需求调研,6.1,6.10,完成现场调研和需求确认&#10;系统部署,6.11,6.30,部署应用和数据库环境"
      />
    </div>
    <template #footer>
      <el-button data-testid="clear-plan-input-button" @click="planInput = ''">清空输入</el-button>
      <el-button @click="importDialogVisible = false">取消</el-button>
      <el-button type="primary" data-testid="generate-gantt-button" @click="generateGanttFromPlan">AI 解析生成甘特图</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="ganttEditVisible" title="编辑任务进度条" width="560px">
    <el-form class="gantt-edit-form" label-position="top">
      <el-form-item label="任务名称">
        <el-input v-model="ganttEditForm.text" data-testid="gantt-edit-name" placeholder="例如：试点社区需求调研" />
      </el-form-item>
      <div class="gantt-edit-grid">
        <el-form-item label="开始日期">
          <el-input v-model="ganttEditForm.startDate" data-testid="gantt-edit-start-date" placeholder="2026-05-25" />
        </el-form-item>
        <el-form-item label="结束日期">
          <el-input v-model="ganttEditForm.endDate" data-testid="gantt-edit-end-date" placeholder="2026-05-29" />
        </el-form-item>
      </div>
      <el-form-item label="任务完成状态">
        <el-select v-model="ganttEditForm.status" data-testid="gantt-edit-status" placeholder="选择任务完成状态">
          <el-option
            v-for="option in ganttStatusOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="负责人">
        <el-input v-model="ganttEditForm.owner" data-testid="gantt-edit-owner" placeholder="可补充负责人姓名" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input
          v-model="ganttEditForm.note"
          type="textarea"
          data-testid="gantt-edit-note"
          :rows="3"
          placeholder="可补充交付物、风险、依赖或其他说明"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="ganttEditVisible = false">取消</el-button>
      <el-button type="primary" data-testid="save-gantt-bar-button" @click="saveGanttBarEdit">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="detailVisible" width="720px" :title="`${detailMetric || '项目'}详情`">
    <div v-if="detailProject" v-loading="assetStore.loading" class="selected-panel project-detail-dialog">
      <div class="panel-head">
        <h3>{{ detailProject.name }}</h3>
      </div>

      <div v-if="detailMetric === '任务'" class="dashboard-detail-list">
        <article v-for="task in assetStore.tasks" :key="task.id" class="dashboard-detail-item">
          <div>
            <strong>{{ task.title }}</strong>
            <p>{{ task.description || '暂无任务说明。' }}</p>
          </div>
          <div class="dashboard-detail-meta">
            <el-tag size="small" :type="task.status === 'done' ? 'success' : task.status === 'doing' ? 'primary' : 'warning'">
              {{ statusLabel[task.status] || task.status }}
            </el-tag>
            <span>责任人：{{ task.owner || '待分配' }}</span>
            <span>截止：{{ task.due_date || '未设置' }}</span>
          </div>
          <el-progress :percentage="task.progress" :stroke-width="7" />
        </article>
        <el-empty v-if="assetStore.tasks.length === 0" description="暂无任务明细" :image-size="80" />
      </div>

      <div v-else-if="detailMetric === '风险'" class="dashboard-detail-list">
        <article v-for="risk in assetStore.risks" :key="risk.id" class="dashboard-detail-item">
          <div class="dashboard-detail-title">
            <strong>{{ risk.title }}</strong>
            <el-tag size="small" :type="risk.impact === '高' ? 'danger' : risk.impact === '中' ? 'warning' : 'info'">
              {{ risk.impact || '未标记' }}
            </el-tag>
          </div>
          <p>{{ risk.description || '暂无风险说明。' }}</p>
          <div class="dashboard-detail-meta">
            <span>概率：{{ risk.probability || '未标记' }}</span>
            <span>状态：{{ risk.status || '未标记' }}</span>
          </div>
          <div class="dashboard-response">
            <el-icon><Warning /></el-icon>
            <span>{{ risk.response || '建议尽快明确责任人、缓解措施和关闭口径。' }}</span>
          </div>
        </article>
        <el-empty v-if="assetStore.risks.length === 0" description="暂无风险明细" :image-size="80" />
      </div>

      <div v-else class="dashboard-health-detail">
        <div class="dashboard-health-grid">
          <div>
            <span>健康分</span>
            <el-tooltip placement="top" effect="light" popper-class="health-breakdown-tooltip">
              <template #content>
                <div class="health-breakdown-content">
                  <strong>健康分计算过程</strong>
                  <p v-for="line in healthExplanationLines(detailProject)" :key="line">{{ line }}</p>
                </div>
              </template>
              <strong class="health-score-hover">{{ detailProject.health }}</strong>
            </el-tooltip>
            <small>悬停查看扣分</small>
          </div>
          <div>
            <span>平均任务进度</span>
            <strong>{{ assetStore.riskSummary?.avg_task_progress ?? detailProject.progress }}%</strong>
          </div>
          <div>
            <span>开放风险</span>
            <strong>{{ assetStore.riskSummary?.open_count ?? detailProject.risks }}</strong>
          </div>
          <div>
            <span>延期任务</span>
            <strong>{{ assetStore.riskSummary?.overdue_tasks ?? 0 }}</strong>
          </div>
        </div>
        <div class="selected-list">
          <div class="dashboard-milestone-panel">
            <el-icon><Calendar /></el-icon>
            <div v-if="assetStore.milestones.length" class="dashboard-milestone-list">
              <div
                v-for="milestone in assetStore.milestones"
                :key="milestone.id"
                class="dashboard-milestone-item"
              >
                <button type="button" class="dashboard-milestone-main" @click="openMilestoneDetail(milestone)">
                  <strong>{{ milestone.title }}</strong>
                  <span>{{ milestone.date || '未设置日期' }}</span>
                  <el-tag size="small" :type="milestone.status === '已完成' ? 'success' : 'info'">
                    {{ milestone.status || '待确认' }}
                  </el-tag>
                </button>
                <el-button
                  class="dashboard-milestone-delete"
                  :icon="Delete"
                  size="small"
                  text
                  type="danger"
                  title="删除里程碑"
                  aria-label="删除里程碑"
                  @click.stop="removeMilestone(milestone)"
                />
              </div>
            </div>
            <span v-else>暂无里程碑</span>
          </div>
          <div>
            <el-icon><TrendCharts /></el-icon>
            <span>预算使用率 {{ detailProject.budget_usage }}%，合同金额 {{ detailProject.budget }}，已发生成本 {{ detailProject.incurred_cost || '未填写' }}</span>
          </div>
          <div>
            <el-icon><Warning /></el-icon>
            <span>{{ detailProject.tasks }} 个任务，{{ detailProject.risks }} 个风险，{{ detailProject.new_demands }} 个新增需求</span>
          </div>
        </div>
      </div>
    </div>
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
