<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CircleCheck, WarnTriangleFilled } from '@element-plus/icons-vue'

import { fetchHealth, type HealthResponse } from '@/api/health'

const loading = ref(true)
const error = ref('')
const health = ref<HealthResponse | null>(null)

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '健康检查失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="health-card">
    <div class="health-title">
      <el-icon :class="error ? 'danger' : 'success'">
        <WarnTriangleFilled v-if="error" />
        <CircleCheck v-else />
      </el-icon>
      <div>
        <strong>后端健康检查</strong>
        <span>P0 API 连通状态</span>
      </div>
    </div>

    <el-skeleton v-if="loading" :rows="3" animated />
    <el-alert v-else-if="error" type="error" :title="error" :closable="false" />
    <dl v-else-if="health" class="health-grid">
      <div>
        <dt>服务</dt>
        <dd>{{ health.service }}</dd>
      </div>
      <div>
        <dt>状态</dt>
        <dd>{{ health.status }}</dd>
      </div>
      <div>
        <dt>数据库</dt>
        <dd>{{ health.database_ready ? '已初始化' : '未就绪' }}</dd>
      </div>
    </dl>
  </section>
</template>
