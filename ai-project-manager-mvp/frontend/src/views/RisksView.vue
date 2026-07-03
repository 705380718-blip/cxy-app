<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Delete, TrendCharts, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useAssetStore } from '@/stores/assets'
import { useProjectStore } from '@/stores/projects'
import type { Demand, Risk } from '@/api/assets'

const assetStore = useAssetStore()
const projectStore = useProjectStore()
const emit = defineEmits<{
  navigate: [view: string]
}>()
const currentProjectKey = computed(() => projectStore.selectedProject?.key || '')
const riskDetailVisible = ref(false)
const demandDetailVisible = ref(false)
const selectedRisk = ref<Risk | null>(null)
const selectedDemand = ref<Demand | null>(null)
const riskStatusFilter = ref('')
const riskImpactFilter = ref('')
const riskProbabilityFilter = ref('')
const riskSourceFilter = ref('')
const demandStatusFilter = ref('')
const demandSourceFilter = ref('')
const riskPage = ref(1)
const demandPage = ref(1)
const demandStatusUpdating = ref('')
const demandDeleting = ref<number | null>(null)
const pageSize = 10
const demandStatusSteps = ['待评估', '评估中', '已完成', '已纳入计划', '暂缓', '已关闭']
const sourceTypeOptions = [
  { value: 'meeting', label: '会议纪要' },
  { value: 'chat', label: '聊天记录' },
  { value: 'report', label: '日报/周报' },
]
const sourceTypeLabelMap = Object.fromEntries(sourceTypeOptions.map((option) => [option.value, option.label]))
const demandActionLabel: Record<string, string> = {
  assessment: '去创建评估任务',
  '已完成': '评估完成',
  '已纳入计划': '纳入计划',
  '暂缓': '暂缓跟进',
  '已关闭': '关闭需求',
}

const riskMetrics = computed(() => [
  ['开放风险', assetStore.riskSummary?.open_count ?? 0, '仍需跟进'],
  ['高影响风险', assetStore.riskSummary?.high_count ?? 0, '优先处理'],
  ['延期任务', assetStore.riskSummary?.overdue_tasks ?? 0, '影响排期'],
  ['新增需求', assetStore.riskSummary?.demand_count ?? 0, '需评估范围'],
])

const project = computed(() => projectStore.selectedProject)
const budgetUsage = computed(() => project.value?.budget_usage ?? 0)
const healthScore = computed(() => assetStore.riskSummary?.health || project.value?.health || 0)

function uniqueValues(values: string[]) {
  return Array.from(new Set(values.filter(Boolean))).sort()
}

function stableOptions(defaults: string[], values: string[]) {
  const seen = new Set<string>()
  return [...defaults, ...values].filter((value) => {
    if (!value || seen.has(value)) return false
    seen.add(value)
    return true
  })
}

function riskSourceLabel(risk: { source_extraction_id?: number | null }) {
  return risk.source_extraction_id ? '信息归集' : '手工维护/示例数据'
}

function demandSourceLabel(demand: { source_type?: string; source_extraction_id?: number | null }) {
  if (demand.source_type === 'assistant') return '来源：AI 助手待确认'
  if (demand.source_type && sourceTypeLabelMap[demand.source_type]) {
    return `来源：${sourceTypeLabelMap[demand.source_type]}`
  }
  if (demand.source_extraction_id) return '来源：信息归集'
  return '来源：手工维护/示例数据'
}

function demandSourceValue(demand: Demand) {
  return demandSourceLabel(demand).replace('来源：', '')
}

function demandStatusTagType(status: string) {
  if (status === '已完成') return 'success'
  if (status === '已纳入计划') return 'success'
  if (status === '评估中') return 'warning'
  if (status === '暂缓') return 'info'
  if (status === '已关闭') return 'danger'
  return 'primary'
}

const riskStatusOptions = computed(() => uniqueValues(assetStore.risks.map((risk) => risk.status)))
const riskImpactOptions = computed(() => uniqueValues(assetStore.risks.map((risk) => risk.impact)))
const riskProbabilityOptions = computed(() => uniqueValues(assetStore.risks.map((risk) => risk.probability)))
const riskSourceOptions = computed(() => uniqueValues(assetStore.risks.map((risk) => riskSourceLabel(risk))))
const demandStatusOptions = computed(() =>
  stableOptions(demandStatusSteps, assetStore.demands.map((demand) => demand.status)),
)
const demandSourceOptions = sourceTypeOptions

const filteredRisks = computed(() =>
  assetStore.risks.filter((risk) =>
    (!riskStatusFilter.value || risk.status === riskStatusFilter.value)
    && (!riskImpactFilter.value || risk.impact === riskImpactFilter.value)
    && (!riskProbabilityFilter.value || risk.probability === riskProbabilityFilter.value)
    && (!riskSourceFilter.value || riskSourceLabel(risk) === riskSourceFilter.value),
  ),
)

const pagedRisks = computed(() => {
  const start = (riskPage.value - 1) * pageSize
  return filteredRisks.value.slice(start, start + pageSize)
})

const filteredDemands = computed(() =>
  assetStore.demands.filter((demand) =>
    (!demandStatusFilter.value || demand.status === demandStatusFilter.value)
    && (!demandSourceFilter.value || demandSourceValue(demand) === demandSourceFilter.value),
  ),
)

const pagedDemands = computed(() => {
  const start = (demandPage.value - 1) * pageSize
  return filteredDemands.value.slice(start, start + pageSize)
})

function openRiskDetail(risk: Risk) {
  selectedRisk.value = risk
  riskDetailVisible.value = true
}

function openDemandDetail(demand: Demand) {
  selectedDemand.value = demand
  demandDetailVisible.value = true
}

function refreshSelectedDemand(demandId: number) {
  selectedDemand.value = assetStore.demands.find((demand) => demand.id === demandId) ?? selectedDemand.value
}

function buildDemandAssessmentAdvice(demand: Demand) {
  const scope = demand.scope_impact || '范围待评估'
  const source = demandSourceValue(demand)
  return [
    `AI 评估建议：该需求当前状态为“${demand.status || '待评估'}”，范围判断为“${scope}”，来源为“${source}”。`,
    '建议先确认业务目标、涉及人员、数据口径和验收标准，再拆解实施任务。',
    '评估时重点关注三件事：是否需要新增数据采集或系统对接、是否影响既有流程和权限、是否会引入额外排期或预算成本。',
  ].join('\n')
}

watch(currentProjectKey, (key) => {
  riskPage.value = 1
  demandPage.value = 1
  if (key) assetStore.refresh(key)
})

watch([riskStatusFilter, riskImpactFilter, riskProbabilityFilter, riskSourceFilter], () => {
  riskPage.value = 1
})

watch([demandStatusFilter, demandSourceFilter], () => {
  demandPage.value = 1
})

onMounted(() => {
  if (currentProjectKey.value) assetStore.refresh(currentProjectKey.value)
})

async function closeRisk(risk: Risk) {
  await assetStore.patchRisk(risk, { status: '已解决' })
  await projectStore.refresh()
  selectedRisk.value = assetStore.risks.find((item) => item.id === risk.id) ?? selectedRisk.value
  ElMessage.success('风险已标记为已解决')
}

async function deleteDemandCard(demand: Demand) {
  try {
    await ElMessageBox.confirm(
      `确定删除新增需求“${demand.title}”吗？删除后不可恢复。`,
      '删除新增需求',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  demandDeleting.value = demand.id
  try {
    await assetStore.removeDemand(demand)
    await projectStore.refresh()
    if (selectedDemand.value?.id === demand.id) {
      selectedDemand.value = null
      demandDetailVisible.value = false
    }
    const maxPage = Math.max(1, Math.ceil(filteredDemands.value.length / pageSize))
    if (demandPage.value > maxPage) demandPage.value = maxPage
    ElMessage.success('新增需求已删除')
  } catch (err) {
    ElMessage.error(err instanceof Error ? `新增需求删除失败：${err.message}` : '新增需求删除失败')
  } finally {
    demandDeleting.value = null
  }
}

async function createDemandAssessmentTask() {
  if (!selectedDemand.value) return
  const demand = selectedDemand.value
  const advice = buildDemandAssessmentAdvice(demand)
  assetStore.prepareTaskDraft({
    demandId: demand.id,
    advice,
    task: {
      project_key: demand.project_key,
      status: 'todo',
      title: `评估需求：${demand.title}`,
      description: [
        demand.description,
        demand.scope_impact ? `范围影响：${demand.scope_impact}` : '',
        demand.source_text ? `原始信息：${demand.source_text}` : '',
        advice,
      ].filter(Boolean).join('\n\n'),
      owner: '待分配',
      start_date: '',
      due_date: '',
      progress: 0,
      source_extraction_id: demand.source_extraction_id ?? null,
      demand_id: demand.id,
    },
  })
  demandDetailVisible.value = false
  emit('navigate', 'tasks')
  ElMessage.info('已带入需求信息，请补充负责人和排期后保存')
}

async function handleDemandAction(command: string) {
  if (command === 'assessment') {
    await createDemandAssessmentTask()
    return
  }
  await updateDemandStatus(command)
}

async function updateDemandStatus(status: string) {
  if (!selectedDemand.value) return
  const demand = selectedDemand.value
  if (demand.status === status) return

  demandStatusUpdating.value = status
  selectedDemand.value = { ...demand, status }
  const demandIndex = assetStore.demands.findIndex((item) => item.id === demand.id)
  const originalDemand = demandIndex >= 0 ? assetStore.demands[demandIndex] : null
  if (originalDemand) {
    assetStore.demands[demandIndex] = { ...originalDemand, status }
  }

  try {
    await assetStore.patchDemand(demand, { status })
    await projectStore.refresh()
    refreshSelectedDemand(demand.id)
    ElMessage.success(`需求已标记为${status}`)
  } catch (err) {
    selectedDemand.value = demand
    if (originalDemand) {
      assetStore.demands[demandIndex] = originalDemand
    }
    ElMessage.error(err instanceof Error ? `需求状态更新失败：${err.message}` : '需求状态更新失败')
  } finally {
    demandStatusUpdating.value = ''
  }
}
</script>

<template>
  <section class="module-toolbar">
    <el-select v-model="projectStore.selectedKey" placeholder="选择项目" class="project-select">
      <el-option
        v-for="item in projectStore.projects"
        :key="item.key"
        :label="item.name"
        :value="item.key"
      />
    </el-select>
    <el-tag type="warning">风险与成本联动</el-tag>
  </section>

  <section class="risk-layout">
    <div class="panel risk-score-panel">
      <div class="panel-head">
        <h3><el-icon><TrendCharts /></el-icon> 项目健康</h3>
        <el-tag :type="healthScore >= 80 ? 'success' : 'warning'">{{ healthScore }} 分</el-tag>
      </div>
      <div class="risk-gauges">
        <div>
          <span>预算使用率</span>
          <strong>{{ budgetUsage }}%</strong>
          <el-progress :percentage="budgetUsage" :stroke-width="10" />
        </div>
        <div>
          <span>风险压力</span>
          <strong>{{ assetStore.riskSummary?.open_count ?? 0 }} 项</strong>
          <el-progress :percentage="Math.min((assetStore.riskSummary?.open_count ?? 0) * 18, 100)" status="warning" :stroke-width="10" />
        </div>
      </div>
    </div>

    <div class="risk-metrics">
      <div v-for="metric in riskMetrics" :key="metric[0]" class="compact-metric">
        <span>{{ metric[0] }}</span>
        <strong>{{ metric[1] }}</strong>
        <small>{{ metric[2] }}</small>
      </div>
    </div>
  </section>

  <section class="workspace-grid">
    <div class="panel">
      <div class="panel-head">
        <h3><el-icon><Warning /></el-icon> 风险清单</h3>
        <el-tag>{{ filteredRisks.length }} / {{ assetStore.risks.length }} 条</el-tag>
      </div>
      <div class="list-controls">
        <el-select v-model="riskStatusFilter" clearable placeholder="状态" size="small">
          <el-option v-for="option in riskStatusOptions" :key="option" :label="option" :value="option" />
        </el-select>
        <el-select v-model="riskImpactFilter" clearable placeholder="影响" size="small">
          <el-option v-for="option in riskImpactOptions" :key="option" :label="option" :value="option" />
        </el-select>
        <el-select v-model="riskProbabilityFilter" clearable placeholder="概率" size="small">
          <el-option v-for="option in riskProbabilityOptions" :key="option" :label="option" :value="option" />
        </el-select>
        <el-select v-model="riskSourceFilter" clearable placeholder="来源" size="small">
          <el-option v-for="option in riskSourceOptions" :key="option" :label="option" :value="option" />
        </el-select>
      </div>
      <el-table
        v-loading="assetStore.loading"
        :data="pagedRisks"
        class="risk-detail-table"
        @row-click="openRiskDetail"
      >
        <el-table-column label="风险" min-width="260">
          <template #default="{ row }">
            <strong>{{ row.title }}</strong>
            <p class="table-sub">{{ row.description }}</p>
          </template>
        </el-table-column>
        <el-table-column prop="probability" label="概率" width="90" />
        <el-table-column prop="impact" label="影响" width="90" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="demandStatusTagType(row.status)">
              {{ row.status || '待评估' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" :disabled="row.status === '已解决'" :data-testid="`close-risk-${row.id}`" @click.stop="closeRisk(row)">解决</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="filteredRisks.length > pageSize" class="table-pagination">
        <el-pagination
          v-model:current-page="riskPage"
          :page-size="pageSize"
          layout="prev, pager, next, total"
          :total="filteredRisks.length"
        />
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <h3>新增需求</h3>
        <el-tag type="info">{{ filteredDemands.length }} / {{ assetStore.demands.length }} 条</el-tag>
      </div>
      <div class="list-controls">
        <el-select v-model="demandStatusFilter" clearable placeholder="状态" size="small">
          <el-option v-for="option in demandStatusOptions" :key="option" :label="option" :value="option" />
        </el-select>
        <el-select v-model="demandSourceFilter" clearable placeholder="来源" size="small">
          <el-option v-for="option in demandSourceOptions" :key="option.value" :label="option.label" :value="option.label" />
        </el-select>
      </div>
      <div class="demand-list">
        <article
          v-for="demand in pagedDemands"
          :key="demand.id"
          class="demand-card risk-detail-trigger"
          @click="openDemandDetail(demand)"
        >
          <div class="demand-card-head">
            <strong>{{ demand.title }}</strong>
            <el-button
              class="demand-card-delete"
              type="danger"
              text
              circle
              :icon="Delete"
              :loading="demandDeleting === demand.id"
              title="删除新增需求"
              aria-label="删除新增需求"
              @click.stop="deleteDemandCard(demand)"
            />
          </div>
          <p>{{ demand.description }}</p>
          <div class="demand-meta">
            <el-tag size="small" :type="demandStatusTagType(demand.status)">
              {{ demand.status || '待评估' }}
            </el-tag>
            <el-tag v-if="demand.scope_impact" size="small" type="info">{{ demand.scope_impact }}</el-tag>
            <el-tag size="small" type="info">{{ demandSourceLabel(demand) }}</el-tag>
          </div>
          <small v-if="demand.source_text" class="demand-source">{{ demand.source_text }}</small>
        </article>
      </div>
      <el-empty v-if="filteredDemands.length === 0" description="暂无新增需求" :image-size="80" />
      <div v-if="filteredDemands.length > pageSize" class="table-pagination">
        <el-pagination
          v-model:current-page="demandPage"
          :page-size="pageSize"
          layout="prev, pager, next, total"
          :total="filteredDemands.length"
        />
      </div>
    </div>
  </section>

  <el-dialog v-model="riskDetailVisible" :title="selectedRisk ? `风险详情 · ${selectedRisk.title}` : '风险详情'" width="720px">
    <div v-if="selectedRisk" class="risk-detail-dialog">
      <section class="risk-detail-hero">
        <div>
          <span>风险状态</span>
          <strong>{{ selectedRisk.status || '待跟进' }}</strong>
        </div>
        <el-tag :type="selectedRisk.status === '已解决' ? 'success' : 'warning'">{{ selectedRisk.impact || '未评估' }}影响</el-tag>
      </section>

      <section class="risk-detail-grid">
        <div>
          <span>发生概率</span>
          <strong>{{ selectedRisk.probability || '未评估' }}</strong>
        </div>
        <div>
          <span>影响等级</span>
          <strong>{{ selectedRisk.impact || '未评估' }}</strong>
        </div>
        <div>
          <span>来源</span>
          <strong>{{ selectedRisk.source_extraction_id ? `信息归集 #${selectedRisk.source_extraction_id}` : '手工维护/示例数据' }}</strong>
        </div>
      </section>

      <section>
        <h4>风险描述</h4>
        <p>{{ selectedRisk.description || '暂无风险描述。' }}</p>
      </section>

      <section>
        <h4>应对措施</h4>
        <p>{{ selectedRisk.response || '暂无应对措施。' }}</p>
      </section>
    </div>
    <template #footer>
      <el-button @click="riskDetailVisible = false">关闭</el-button>
      <el-button
        v-if="selectedRisk"
        type="primary"
        :disabled="selectedRisk.status === '已解决'"
        @click="closeRisk(selectedRisk)"
      >
        标记解决
      </el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="demandDetailVisible" :title="selectedDemand ? `需求详情 · ${selectedDemand.title}` : '需求详情'" width="720px">
    <div v-if="selectedDemand" class="risk-detail-dialog">
      <section class="risk-detail-hero demand-detail-hero">
        <div>
          <span>需求状态</span>
          <strong>{{ selectedDemand.status || '待评估' }}</strong>
        </div>
        <el-tag>{{ selectedDemand.scope_impact || '范围待评估' }}</el-tag>
      </section>

      <section>
        <h4>需求描述</h4>
        <p>{{ selectedDemand.description || '暂无需求描述。' }}</p>
      </section>

      <section class="risk-detail-grid">
        <div>
          <span>来源类型</span>
          <strong>{{ demandSourceLabel(selectedDemand).replace('来源：', '') }}</strong>
        </div>
        <div>
          <span>来源事项</span>
          <strong>{{ selectedDemand.source_title || (selectedDemand.source_extraction_id ? `归集事项 #${selectedDemand.source_extraction_id}` : '无') }}</strong>
        </div>
        <div>
          <span>创建时间</span>
          <strong>{{ selectedDemand.source_created_at || '未记录' }}</strong>
        </div>
      </section>

      <section v-if="selectedDemand.source_text">
        <h4>原始信息</h4>
        <p>{{ selectedDemand.source_text }}</p>
      </section>

      <section>
        <h4>下一步操作</h4>
        <div class="demand-next-actions">
          <div>
            <strong>选择需求下一步</strong>
            <span>根据当前判断进入任务评估、纳入计划、暂缓或关闭。</span>
          </div>
          <el-dropdown
            trigger="click"
            :disabled="Boolean(demandStatusUpdating)"
            @command="handleDemandAction"
          >
            <el-button type="primary">
              {{ demandStatusUpdating ? `${demandActionLabel[demandStatusUpdating] || '更新中'}...` : '选择操作' }}
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  command="assessment"
                  :disabled="selectedDemand.status === '评估中'"
                >
                  去创建评估任务
                </el-dropdown-item>
                <el-dropdown-item
                  command="已完成"
                  :disabled="selectedDemand.status === '已完成'"
                >
                  评估完成
                </el-dropdown-item>
                <el-dropdown-item
                  command="已纳入计划"
                  :disabled="selectedDemand.status === '已纳入计划'"
                >
                  纳入计划
                </el-dropdown-item>
                <el-dropdown-item
                  command="暂缓"
                  :disabled="selectedDemand.status === '暂缓'"
                >
                  暂缓跟进
                </el-dropdown-item>
                <el-dropdown-item
                  command="已关闭"
                  :disabled="selectedDemand.status === '已关闭'"
                  divided
                >
                  关闭需求
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </section>
    </div>
    <template #footer>
      <el-button type="primary" @click="demandDetailVisible = false">知道了</el-button>
    </template>
  </el-dialog>
</template>
