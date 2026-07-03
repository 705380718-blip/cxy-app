<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Check, Edit, Finished, MagicStick, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { useAssetStore } from '@/stores/assets'
import { useInboxStore } from '@/stores/inbox'
import { useProjectStore } from '@/stores/projects'
import type { Extraction, ExtractionPayload, ExtractionType } from '@/api/inbox'

const inboxStore = useInboxStore()
const projectStore = useProjectStore()
const assetStore = useAssetStore()
const editDialogVisible = ref(false)
const editing = ref<Extraction | null>(null)
const inboxStep = ref(0)
const rawForm = reactive({
  source_type: 'meeting',
  raw_text: '',
})
const editForm = reactive<ExtractionPayload>({
  item_type: 'task',
  title: '',
  description: '',
  owner: '',
  due_date: '',
  probability: '',
  impact: '',
  response: '',
})

const currentProjectKey = computed(() => projectStore.selectedProject?.key || '')
const typeMeta: Record<ExtractionType, { label: string; tone: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  task: { label: '任务', tone: 'primary' },
  risk: { label: '风险', tone: 'danger' },
  demand: { label: '需求', tone: 'warning' },
  milestone: { label: '里程碑', tone: 'success' },
}
const inboxMetrics = computed(() => [
  ['待确认', inboxStore.pendingCount, '候选事项'],
  ['任务', inboxStore.typeCount('task'), '可落任务池'],
  ['风险', inboxStore.typeCount('risk'), '可落风险清单'],
  ['需求/里程碑', inboxStore.typeCount('demand') + inboxStore.typeCount('milestone'), '范围与节点'],
])

watch(currentProjectKey, (key) => {
  if (key) inboxStore.refresh(key)
})

onMounted(() => {
  if (currentProjectKey.value) inboxStore.refresh(currentProjectKey.value)
})

function openEdit(extraction: Extraction) {
  editing.value = extraction
  Object.assign(editForm, {
    item_type: extraction.item_type,
    title: extraction.title,
    description: extraction.description,
    owner: extraction.owner,
    due_date: extraction.due_date,
    probability: extraction.probability,
    impact: extraction.impact,
    response: extraction.response,
  })
  editDialogVisible.value = true
}

async function submitExtraction() {
  if (!currentProjectKey.value) {
    ElMessage.warning('请选择项目')
    return
  }
  if (!rawForm.raw_text.trim()) {
    ElMessage.warning('请粘贴会议纪要或聊天记录')
    return
  }
  await inboxStore.submitAndExtract({
    project_key: currentProjectKey.value,
    source_type: rawForm.source_type,
    raw_text: rawForm.raw_text,
  })
  if (!inboxStore.error) {
    inboxStep.value = 1
    ElMessage.success('已生成待确认事项')
  }
}

function finishWorkflow() {
  inboxStep.value = 0
  ElMessage.success('信息归集流程已完成')
}

async function saveEdit() {
  if (!editing.value || !editForm.title?.trim()) {
    ElMessage.warning('请填写标题')
    return
  }
  if (editForm.item_type === 'milestone' && !editForm.due_date?.trim()) {
    ElMessage.warning('里程碑日期为必填项')
    return
  }
  await inboxStore.saveExtraction(editing.value, { ...editForm })
  editDialogVisible.value = false
  ElMessage.success('候选事项已更新')
}

async function confirmItem(extraction: Extraction) {
  if (extraction.item_type === 'milestone' && !extraction.due_date?.trim()) {
    ElMessage.warning('里程碑日期为必填项，请先编辑补充日期')
    openEdit(extraction)
    return
  }
  await inboxStore.confirm(extraction)
  await Promise.all([assetStore.refresh(currentProjectKey.value), projectStore.refresh()])
  ElMessage.success('已确认并落库')
}

async function dismissItem(extraction: Extraction) {
  await inboxStore.dismiss(extraction)
  ElMessage.success('已忽略该候选项')
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
    <el-tag type="success">AI 提取待确认</el-tag>
  </section>

  <section class="task-metrics">
    <div v-for="metric in inboxMetrics" :key="metric[0]" class="compact-metric">
      <span>{{ metric[0] }}</span>
      <strong>{{ metric[1] }}</strong>
      <small>{{ metric[2] }}</small>
    </div>
  </section>

  <section class="panel inbox-workflow-panel">
    <div class="panel-head">
      <h3>信息归集流程</h3>
      <el-tag>{{ inboxStep === 0 ? '录入原文' : '确认落库' }}</el-tag>
    </div>
    <el-steps :active="inboxStep" finish-status="success" align-center class="inbox-steps">
      <el-step title="录入原文" />
      <el-step title="确认落库" />
    </el-steps>

    <div v-if="inboxStep === 0" class="inbox-step-panel">
      <div class="panel-head">
        <h3><el-icon><UploadFilled /></el-icon> 原文归集</h3>
        <el-select v-model="rawForm.source_type" class="source-select">
          <el-option label="会议纪要" value="meeting" />
          <el-option label="聊天记录" value="chat" />
          <el-option label="日报/周报" value="report" />
        </el-select>
      </div>
      <div data-testid="inbox-raw-text">
        <el-input
          v-model="rawForm.raw_text"
          type="textarea"
          :rows="14"
          placeholder="粘贴会议纪要、群聊记录或日报内容..."
        />
      </div>
      <div class="inbox-submit">
        <el-button data-testid="extract-items-button" type="primary" :loading="inboxStore.extracting" :icon="MagicStick" @click="submitExtraction">
          下一步：AI 提取
        </el-button>
      </div>
    </div>

    <div v-else class="inbox-step-panel">
      <div class="panel-head">
        <h3>待确认事项</h3>
        <el-tag type="warning">{{ inboxStore.pendingCount }} 条</el-tag>
      </div>
      <div class="extraction-grid" v-loading="inboxStore.loading">
        <article v-for="item in inboxStore.extractions" :key="item.id" class="extraction-card" :data-testid="`extraction-card-${item.id}`">
          <div class="extraction-head">
            <el-tag :type="typeMeta[item.item_type].tone">{{ typeMeta[item.item_type].label }}</el-tag>
            <span>{{ item.due_date || '无日期' }}</span>
          </div>
          <strong>{{ item.title }}</strong>
          <p>{{ item.description }}</p>
          <div class="extraction-meta">
            <span v-if="item.owner">负责人：{{ item.owner }}</span>
            <span v-if="item.probability">概率：{{ item.probability }}</span>
            <span v-if="item.impact">影响：{{ item.impact }}</span>
          </div>
          <div class="task-actions">
            <el-button size="small" :icon="Edit" :data-testid="`edit-extraction-${item.id}`" @click="openEdit(item)">编辑</el-button>
            <el-button size="small" type="primary" :icon="Check" :data-testid="`confirm-extraction-${item.id}`" @click="confirmItem(item)">确认落库</el-button>
            <el-button size="small" :data-testid="`dismiss-extraction-${item.id}`" @click="dismissItem(item)">忽略</el-button>
          </div>
        </article>
        <el-empty v-if="inboxStore.extractions.length === 0" description="暂无待确认事项" :image-size="96" />
      </div>
      <div class="inbox-submit">
        <el-button data-testid="inbox-prev-button" @click="inboxStep = 0">上一步</el-button>
        <el-button data-testid="finish-inbox-button" type="primary" :icon="Finished" @click="finishWorkflow">完成</el-button>
      </div>
    </div>
  </section>

  <el-dialog v-model="editDialogVisible" title="编辑待确认事项" width="720px">
    <el-form label-position="top" class="task-form">
      <el-form-item label="类型">
        <el-select v-model="editForm.item_type">
          <el-option label="任务" value="task" />
          <el-option label="风险" value="risk" />
          <el-option label="需求" value="demand" />
          <el-option label="里程碑" value="milestone" />
        </el-select>
      </el-form-item>
      <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
      <el-form-item label="负责人"><el-input v-model="editForm.owner" /></el-form-item>
      <el-form-item label="日期"><el-date-picker v-model="editForm.due_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="概率"><el-input v-model="editForm.probability" /></el-form-item>
      <el-form-item label="影响"><el-input v-model="editForm.impact" /></el-form-item>
      <el-form-item label="描述" class="field-full">
        <el-input v-model="editForm.description" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="建议动作" class="field-full">
        <el-input v-model="editForm.response" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="saveEdit">保存</el-button>
    </template>
  </el-dialog>
</template>
