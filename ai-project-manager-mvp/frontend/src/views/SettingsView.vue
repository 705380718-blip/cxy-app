<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Connection, Finished, Operation } from '@element-plus/icons-vue'

import { useSettingsStore } from '@/stores/settings'

const store = useSettingsStore()

const providerOptions = [
  {
    label: '离线内置模型',
    value: 'mock',
    model: 'local-project-assistant',
    base_url: '',
    api_key: '',
  },
  {
    label: 'OpenAI Compatible',
    value: 'openai-compatible',
    model: '',
    base_url: '',
    api_key: '',
  },
  {
    label: '阿里百炼 / 通义千问',
    value: 'dashscope',
    model: 'qwen-plus',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    api_key: '',
  },
  {
    label: 'DeepSeek',
    value: 'deepseek',
    model: 'deepseek-v4-flash',
    base_url: 'https://api.deepseek.com',
    api_key: '',
  },
  {
    label: 'Kimi / Moonshot',
    value: 'moonshot',
    model: 'kimi-k2.6',
    base_url: 'https://api.moonshot.cn/v1',
    api_key: '',
  },
  {
    label: '智谱 GLM',
    value: 'zhipu',
    model: 'glm-4-flash',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    api_key: '',
  },
  {
    label: '火山方舟 / 豆包',
    value: 'volcengine',
    model: 'doubao-seed-1-6',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    api_key: '',
  },
  {
    label: '百度千帆',
    value: 'qianfan',
    model: 'ernie-4.5-turbo-128k',
    base_url: 'https://qianfan.baidubce.com/v2',
    api_key: '',
  },
  {
    label: '腾讯混元',
    value: 'hunyuan',
    model: 'hunyuan-turbos-latest',
    base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
    api_key: '',
  },
  {
    label: '硅基流动',
    value: 'siliconflow',
    model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    base_url: 'https://api.siliconflow.cn/v1',
    api_key: '',
  },
  {
    label: '本地 LM Studio',
    value: 'lm-studio',
    model: 'local-model',
    base_url: 'http://localhost:1234/v1',
    api_key: '',
  },
  {
    label: '本地 Ollama',
    value: 'ollama',
    model: 'qwen2.5:14b',
    base_url: 'http://127.0.0.1:11434',
    api_key: '',
  },
]

const statusType = computed(() => {
  if (store.config?.status === 'connected') return 'success'
  if (store.config?.status === 'failed') return 'danger'
  return 'warning'
})

const statusLabel = computed(() => {
  if (store.config?.status === 'connected') return '已连接'
  if (store.config?.status === 'failed') return '失败'
  return '待测试'
})

type AgentListField = 'responsibilities' | 'forbidden' | 'long_term_preferences' | 'proactive_reminders'

function listToText(items?: string[]) {
  return (items || []).join('\n')
}

function updateAgentList(field: AgentListField, value: string) {
  if (!store.agentProfile) return
  store.agentProfile[field] = value
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function syncProviderLabel() {
  if (!store.config) return
  const option = providerOptions.find((item) => item.value === store.config?.provider)
  if (!option) {
    store.config.provider_label = store.config.provider
    return
  }
  store.config.provider_label = option.label
  store.config.model = option.model || store.config.model
  store.config.base_url = option.base_url
  store.config.api_key = option.api_key
  store.config.verify_ssl = true
  store.config.status = 'untested'
  store.config.status_message = '配置已更新，尚未测试连接。'
  store.config.last_tested_at = ''
}

onMounted(() => {
  if (!store.config) store.load()
})
</script>

<template>
  <section class="settings-grid" v-loading="store.loading">
    <div class="panel">
      <div class="panel-head">
        <h3>
          <el-icon><Operation /></el-icon>
          默认模型配置
        </h3>
        <el-tag :type="statusType">{{ statusLabel }}</el-tag>
      </div>

      <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" class="page-alert" />

      <el-form v-if="store.config" label-position="top" class="model-form">
        <div class="model-form-grid">
          <el-form-item label="模型类型">
            <el-select v-model="store.config.provider" data-testid="provider-select" @change="syncProviderLabel">
              <el-option
                v-for="option in providerOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="模型名称">
            <el-input v-model="store.config.model" data-testid="model-name-input" placeholder="例如 qwen-plus / gpt-4.1-mini" />
          </el-form-item>
          <el-form-item label="API 地址 / 本地地址">
            <el-input
              v-model="store.config.base_url"
              data-testid="model-base-url-input"
              placeholder="https://api.example.com/v1 或 http://127.0.0.1:11434"
            />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input v-model="store.config.api_key" data-testid="model-api-key-input" type="password" show-password placeholder="本地模型可留空" />
          </el-form-item>
        </div>

        <el-form-item label="温度">
          <el-slider v-model="store.config.temperature" :min="0" :max="1" :step="0.1" />
        </el-form-item>

        <el-form-item v-if="store.config.provider !== 'mock'" label="连接安全">
          <div class="ssl-option">
            <el-switch v-model="store.config.verify_ssl" active-text="校验 HTTPS 证书" inactive-text="跳过证书校验" />
            <span>公司代理或自签名证书导致测试失败时，可临时关闭；仅建议本地调试使用。</span>
          </div>
        </el-form-item>

        <div class="settings-actions">
          <el-button data-testid="test-model-button" :icon="Connection" :loading="store.testing" @click="store.test()">测试连通性</el-button>
          <el-button data-testid="save-model-button" type="primary" :icon="Finished" :loading="store.saving" @click="store.save()">保存配置</el-button>
        </div>
      </el-form>
    </div>

    <div class="panel">
      <div class="panel-head">
        <h3>连接状态</h3>
        <el-tag :type="statusType">{{ statusLabel }}</el-tag>
      </div>
      <div v-if="store.config" class="status-list">
        <div class="status-card">
          <strong>{{ store.config.provider_label || store.config.provider }} · {{ statusLabel }}</strong>
          <span>{{ store.config.status_message }}</span>
        </div>
        <div class="status-card">
          <strong>默认模型</strong>
          <span>{{ store.config.model }} 将用于信息归集、文档生成、风险分析和右侧 AI 助手。</span>
        </div>
        <div class="status-card">
          <strong>最近测试</strong>
          <span>{{ store.config.last_tested_at || '暂无测试记录' }}</span>
        </div>
      </div>
    </div>
  </section>

  <section class="panel" v-if="store.agentProfile">
    <div class="panel-head">
      <h3>
        <el-icon><Operation /></el-icon>
        项目管理智能体
      </h3>
      <el-tag type="success">长期保留</el-tag>
    </div>
    <el-alert
      title="智能体配置会保存在本地 SQLite，和模型配置分离；切换模型不会改变小智的身份、规则和项目对话记忆。"
      type="info"
      :closable="false"
      class="page-alert"
    />
    <el-form label-position="top" class="model-form">
      <div class="model-form-grid">
        <el-form-item label="智能体名称">
          <el-input v-model="store.agentProfile.name" data-testid="agent-name-input" placeholder="例如：小智" />
        </el-form-item>
        <el-form-item label="语气风格">
          <el-input v-model="store.agentProfile.tone" data-testid="agent-tone-input" placeholder="例如：理性，沉稳" />
        </el-form-item>
        <el-form-item label="角色定位" class="field-full">
          <el-input v-model="store.agentProfile.role" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="默认输出格式" class="field-full">
          <el-input v-model="store.agentProfile.default_output_format" />
        </el-form-item>
        <el-form-item label="主要职责（一行一个）" class="field-full">
          <el-input
            :model-value="listToText(store.agentProfile.responsibilities)"
            type="textarea"
            :rows="4"
            @update:model-value="updateAgentList('responsibilities', $event)"
          />
        </el-form-item>
        <el-form-item label="需要主动提醒的事项（一行一个）" class="field-full">
          <el-input
            :model-value="listToText(store.agentProfile.proactive_reminders)"
            type="textarea"
            :rows="3"
            @update:model-value="updateAgentList('proactive_reminders', $event)"
          />
        </el-form-item>
        <el-form-item label="长期偏好（一行一个）" class="field-full">
          <el-input
            :model-value="listToText(store.agentProfile.long_term_preferences)"
            type="textarea"
            :rows="3"
            @update:model-value="updateAgentList('long_term_preferences', $event)"
          />
        </el-form-item>
        <el-form-item label="禁止事项（一行一个）" class="field-full">
          <el-input
            :model-value="listToText(store.agentProfile.forbidden)"
            type="textarea"
            :rows="3"
            @update:model-value="updateAgentList('forbidden', $event)"
          />
        </el-form-item>
        <el-form-item label="记忆策略" class="field-full">
          <el-input v-model="store.agentProfile.memory_policy" type="textarea" :rows="2" />
        </el-form-item>
      </div>
      <div class="settings-actions">
        <el-button data-testid="save-agent-button" type="primary" :icon="Finished" :loading="store.savingAgent" @click="store.saveAgent()">
          保存小智配置
        </el-button>
      </div>
    </el-form>
  </section>

  <section class="panel" v-if="store.config">
    <div class="panel-head">
      <h3>高级设置：按能力单独覆盖</h3>
      <el-tag>可选</el-tag>
    </div>
    <div class="override-grid">
      <div v-for="override in store.config.overrides" :key="override.capability" class="override-row">
        <div class="override-name">
          <strong>{{ override.label }}</strong>
          <span>{{ override.mode === 'inherit' ? '继承默认模型' : '单独指定模型' }}</span>
        </div>
        <div class="override-controls">
          <el-select v-model="override.mode">
            <el-option label="继承默认模型" value="inherit" />
            <el-option label="单独指定" value="custom" />
          </el-select>
          <el-input v-model="override.provider" :disabled="override.mode === 'inherit'" placeholder="模型类型" />
          <el-input v-model="override.model" :disabled="override.mode === 'inherit'" placeholder="模型名称" />
          <el-input v-model="override.base_url" :disabled="override.mode === 'inherit'" placeholder="API 地址" />
        </div>
      </div>
    </div>
  </section>
</template>
