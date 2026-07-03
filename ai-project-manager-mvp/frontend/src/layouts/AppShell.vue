<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  ArrowRight,
  DataBoard,
  Document,
  FolderOpened,
  List,
  MagicStick,
  Promotion,
  Setting,
  UserFilled,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import DashboardView from '@/views/DashboardView.vue'
import DocsView from '@/views/DocsView.vue'
import InboxView from '@/views/InboxView.vue'
import ProjectManagementView from '@/views/ProjectManagementView.vue'
import RisksView from '@/views/RisksView.vue'
import SettingsView from '@/views/SettingsView.vue'
import TasksView from '@/views/TasksView.vue'
import { askAssistant, listAssistantMessages } from '@/api/settings'
import { clearSystemData, downloadSystemBackup, downloadSystemData } from '@/api/system'
import { useProjectStore } from '@/stores/projects'
import { useSettingsStore } from '@/stores/settings'

const navItems = [
  { key: 'dashboard', label: '项目驾驶舱', icon: DataBoard, enabled: true },
  { key: 'inbox', label: '信息归集', icon: Document, enabled: true },
  { key: 'docs', label: '智能文档中心', icon: Document, enabled: true },
  { key: 'tasks', label: '任务进度看板', icon: List, enabled: true },
  { key: 'risks', label: '风险与成本', icon: Warning, enabled: true },
  { key: 'projects', label: '项目信息管理', icon: FolderOpened, enabled: true },
  { key: 'settings', label: '模型与 Agent', icon: Setting, enabled: true },
]

const store = useProjectStore()
const settings = useSettingsStore()
const activeView = ref('dashboard')
const activeItem = computed(() => navItems.find((item) => item.key === activeView.value) || navItems[0])
const agentName = computed(() => settings.agentProfile?.name || '小智')
const aiInput = ref('')
const aiLoading = ref(false)
const aiHistoryLoading = ref(false)
const aiHistoryDialogVisible = ref(false)
const aiHistoryDialogLoading = ref(false)
const aiHistoryMessages = ref<{ role: 'ai' | 'user'; text: string; view: string; created_at: string }[]>([])
const aiHistoryProjectName = ref('')
const aiCollapsed = ref(false)
const aiBodyRef = ref<HTMLElement | null>(null)
const aiMessages = ref([
  {
    role: 'ai',
    text: '我是小智，会读取当前项目的任务、风险、需求、里程碑和文档上下文，优先提醒风险、待办和逾期进度。',
  },
])

const quickPrompts = ['这个项目现在最大风险是什么？', '分析当前项目进度', '生成今日日报', '生成本周项目周报']
const currentUser = {
  name: '陈晓勇',
  role: '系统使用者',
  scope: '本地单用户工作台',
}

const projectContextIntro =
  '我是小智，会读取当前项目的任务、风险、需求、里程碑和文档上下文，优先提醒风险、待办和逾期进度。可以问我最大风险、下一步排期或周报要点。'
const noProjectAssistantText =
  '我是小智。当前还没有项目，暂时无法读取项目上下文。请先在“项目信息管理”中新建项目，之后我就能基于项目任务、风险、需求、里程碑和文档提供提醒与顾问建议。'

function scrollAiToBottom() {
  nextTick(() => {
    const body = aiBodyRef.value
    if (body) body.scrollTop = body.scrollHeight
  })
}

async function loadAssistantHistory() {
  const project = store.selectedProject
  if (!project) {
    aiMessages.value = [
      {
        role: 'ai',
        text: noProjectAssistantText,
      },
    ]
    scrollAiToBottom()
    return
  }
  aiHistoryLoading.value = true
  try {
    const messages = await listAssistantMessages(project.key, 12)
    aiMessages.value = messages.length
      ? messages.map((message) => ({
          role: message.role === 'assistant' ? 'ai' : 'user',
          text: message.content,
        }))
      : [
          {
            role: 'ai',
            text: projectContextIntro,
          },
        ]
  } catch {
    aiMessages.value = [
      {
        role: 'ai',
        text: '历史消息加载失败，但你仍然可以继续提问，我会基于当前项目上下文回答。',
      },
    ]
  } finally {
    aiHistoryLoading.value = false
    scrollAiToBottom()
  }
}

async function openAssistantHistory() {
  const project = store.selectedProject
  if (!project) {
    ElMessage.warning('请先新建或选择项目')
    return
  }
  aiHistoryProjectName.value = project.name
  aiHistoryDialogVisible.value = true
  aiHistoryDialogLoading.value = true
  try {
    const messages = await listAssistantMessages(project.key, 80)
    aiHistoryMessages.value = messages.map((message) => ({
      role: message.role === 'assistant' ? 'ai' : 'user',
      text: message.content,
      view: message.view,
      created_at: message.created_at,
    }))
  } catch (err) {
    ElMessage.error(err instanceof Error ? `对话记录加载失败：${err.message}` : '对话记录加载失败')
  } finally {
    aiHistoryDialogLoading.value = false
  }
}

async function sendPrompt(prompt?: string) {
  const text = (prompt || aiInput.value).trim()
  if (!text) return
  aiMessages.value.push({ role: 'user', text })
  scrollAiToBottom()
  aiInput.value = ''
  const project = store.selectedProject
  if (!project) {
    aiMessages.value.push({ role: 'ai', text: noProjectAssistantText })
    scrollAiToBottom()
    return
  }
  aiLoading.value = true
  try {
    const response = await askAssistant({
      project_key: project.key,
      view: activeItem.value.label,
      message: text,
    })
    aiMessages.value.push({ role: 'ai', text: response.answer })
    if (response.action_type === 'pending_extraction') {
      aiMessages.value.push({ role: 'ai', text: '待确认事项已进入信息归集页，可以在那里编辑后确认落库。' })
    }
    scrollAiToBottom()
  } catch (err) {
    aiMessages.value.push({
      role: 'ai',
      text: err instanceof Error ? `助手请求失败：${err.message}` : '助手请求失败，请稍后重试。',
    })
    scrollAiToBottom()
  } finally {
    aiLoading.value = false
  }
}

async function exportData() {
  try {
    await downloadSystemData()
    ElMessage.success('系统数据已开始导出')
  } catch (err) {
    ElMessage.error(err instanceof Error ? `导出失败：${err.message}` : '导出失败')
  }
}

async function clearData() {
  try {
    await ElMessageBox.confirm(
      '清空后项目、任务、风险、信息归集、文档模板、生成历史和聊天记录都会被删除。系统会先自动生成备份，是否继续？',
      '清空系统数据',
      {
        type: 'warning',
        confirmButtonText: '清空数据',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
    const result = await clearSystemData()
    activeView.value = 'dashboard'
    aiMessages.value = [
      {
        role: 'ai',
        text: '系统数据已清空。你可以在项目信息管理中新建项目，或通过重置脚本恢复演示数据。',
      },
    ]
    await Promise.all([store.refresh(), settings.load()])
    ElMessage.success('系统数据已清空，备份已保存')
    try {
      await ElMessageBox.confirm(`备份文件已保存：${result.backup_path}`, '清空前备份已生成', {
        type: 'success',
        confirmButtonText: '下载备份',
        cancelButtonText: '稍后处理',
      })
      await downloadSystemBackup(result.backup_url, result.backup_name)
    } catch (downloadChoice) {
      if (downloadChoice !== 'cancel' && downloadChoice !== 'close') {
        ElMessage.error(downloadChoice instanceof Error ? `备份下载失败：${downloadChoice.message}` : '备份下载失败')
      }
    }
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    ElMessage.error(err instanceof Error ? `清空失败：${err.message}` : '清空失败')
  }
}

function handleUserCommand(command: string) {
  if (command === 'export') {
    exportData()
    return
  }
  if (command === 'clear') {
    clearData()
  }
}

onMounted(() => {
  store.refresh().then(loadAssistantHistory)
  settings.load()
})

watch(
  () => store.selectedKey,
  () => {
    loadAssistantHistory()
  },
)
</script>

<template>
  <div class="app-shell" :class="{ 'ai-collapsed': aiCollapsed }">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">
          <el-icon><MagicStick /></el-icon>
        </div>
        <div>
          <h1>AI项目经理助手</h1>
        </div>
      </div>

      <nav class="nav-list">
        <button
          v-for="item in navItems"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeView === item.key, disabled: !item.enabled }"
          :data-testid="`nav-${item.key}`"
          :disabled="!item.enabled"
          @click="activeView = item.key"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <el-dropdown trigger="click" placement="top-start" @command="handleUserCommand">
        <button class="sidebar-user" data-testid="sidebar-user-menu">
          <div class="sidebar-user-avatar">
            <el-icon><UserFilled /></el-icon>
          </div>
          <div class="sidebar-user-meta">
            <span>{{ currentUser.role }}</span>
            <strong>{{ currentUser.name }}</strong>
            <small>{{ currentUser.scope }}</small>
          </div>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="export">导出系统数据</el-dropdown-item>
            <el-dropdown-item command="clear" divided>清空系统数据</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <h2>{{ activeItem.label }}</h2>
        </div>
      </header>

      <el-alert v-if="store.error" type="error" :title="store.error" :closable="false" class="page-alert" />

      <DashboardView v-if="activeView === 'dashboard'" />
      <InboxView v-else-if="activeView === 'inbox'" />
      <DocsView v-else-if="activeView === 'docs'" />
      <TasksView v-else-if="activeView === 'tasks'" />
      <RisksView v-else-if="activeView === 'risks'" @navigate="activeView = $event" />
      <ProjectManagementView v-else-if="activeView === 'projects'" />
      <SettingsView v-else-if="activeView === 'settings'" />
    </main>

    <aside class="ai-panel">
      <div class="ai-head">
        <div v-if="!aiCollapsed" class="ai-icon">
          <el-icon><MagicStick /></el-icon>
        </div>
        <div v-if="!aiCollapsed">
          <strong>{{ agentName }}</strong>
          <span>上下文：{{ activeItem.label }} · {{ store.selectedProject?.name || '暂无项目' }}</span>
        </div>
        <button class="ai-toggle" :title="aiCollapsed ? `展开 ${agentName}` : `收起 ${agentName}`" @click="aiCollapsed = !aiCollapsed">
          <el-icon><ArrowRight v-if="!aiCollapsed" /><ArrowLeft v-else /></el-icon>
        </button>
      </div>
      <template v-if="!aiCollapsed">
        <div class="quick-grid">
          <button v-for="prompt in quickPrompts" :key="prompt" class="quick-action" @click="sendPrompt(prompt)">
            {{ prompt }}
          </button>
        </div>
        <div ref="aiBodyRef" class="ai-body">
          <div v-for="(message, index) in aiMessages" :key="`${message.role}-${index}-${message.text}`" class="ai-message" :class="message.role">
            {{ message.text }}
          </div>
          <div v-if="aiHistoryLoading" class="ai-message ai">正在加载对话历史...</div>
          <div v-if="aiLoading" class="ai-message ai">正在读取项目上下文...</div>
        </div>
        <div class="ai-foot">
          <el-input
            data-testid="ai-input"
            v-model="aiInput"
            placeholder="输入问题或指令..."
            :disabled="aiLoading"
            @keyup.enter="sendPrompt()"
          />
          <el-button data-testid="ai-history-button" :icon="Document" title="对话记录" @click="openAssistantHistory" />
          <el-button data-testid="ai-send-button" type="primary" :icon="Promotion" :loading="aiLoading" @click="sendPrompt()" />
        </div>
      </template>
    </aside>

    <el-dialog v-model="aiHistoryDialogVisible" :title="`对话记录 · ${aiHistoryProjectName || '当前项目'}`" width="680px">
      <div v-loading="aiHistoryDialogLoading" class="ai-history-list">
        <div v-for="(message, index) in aiHistoryMessages" :key="`${message.created_at}-${index}`" class="ai-history-item" :class="message.role">
          <div>
            <strong>{{ message.role === 'ai' ? agentName : '我' }}</strong>
            <span>{{ message.view }} · {{ message.created_at }}</span>
          </div>
          <p>{{ message.text }}</p>
        </div>
        <el-empty v-if="!aiHistoryDialogLoading && aiHistoryMessages.length === 0" description="暂无对话记录" :image-size="80" />
      </div>
      <template #footer>
        <el-button @click="aiHistoryDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>
