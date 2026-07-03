<script setup lang="ts">
import { reactive, ref } from 'vue'
import { Delete, Edit, FolderAdd, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { emptyProject, useProjectStore } from '@/stores/projects'
import type { Project, ProjectPayload } from '@/api/projects'

const store = useProjectStore()
const search = ref('')
const dialogVisible = ref(false)
const editingKey = ref('')
const form = reactive<ProjectPayload>(emptyProject())

function resetForm(payload: ProjectPayload = emptyProject()) {
  Object.assign(form, payload)
}

function openCreate() {
  editingKey.value = ''
  resetForm()
  dialogVisible.value = true
}

function openEdit(project: Project) {
  editingKey.value = project.key
  resetForm({ ...project })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写项目名称')
    return
  }
  await store.saveProject({ ...form }, editingKey.value || undefined)
  dialogVisible.value = false
  ElMessage.success(editingKey.value ? '项目已更新' : '项目已新增')
}

async function remove(project: Project) {
  await ElMessageBox.confirm(`确定删除「${project.name}」吗？`, '删除项目', { type: 'warning' })
  await store.removeProject(project.key)
  ElMessage.success('项目已删除')
}

async function searchProjects() {
  await store.refresh(search.value)
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h3>项目信息管理</h3>
      <div class="toolbar">
        <el-input v-model="search" placeholder="搜索项目、客户、地区、负责人..." clearable @keyup.enter="searchProjects">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button @click="searchProjects">搜索</el-button>
        <el-button type="primary" :icon="FolderAdd" @click="openCreate">新增项目</el-button>
      </div>
    </div>

    <el-table v-loading="store.loading" :data="store.projects" class="project-table">
      <el-table-column label="项目" min-width="260">
        <template #default="{ row }">
          <strong>{{ row.name }}</strong>
          <p class="table-sub">{{ row.customer }} · {{ row.region }} · {{ row.project_type }}</p>
        </template>
      </el-table-column>
      <el-table-column prop="phase" label="阶段" width="110" />
      <el-table-column prop="contract_status" label="合同" width="120" />
      <el-table-column prop="manager" label="项目经理" width="110" />
      <el-table-column label="进度" width="150">
        <template #default="{ row }">
          <el-progress :percentage="row.progress" :stroke-width="8" />
        </template>
      </el-table-column>
      <el-table-column label="驾驶舱" width="110">
        <template #default="{ row }">
          <el-switch :model-value="row.dashboard" @change="store.toggleDashboard(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130">
        <template #default="{ row }">
          <el-button :icon="Edit" circle @click="openEdit(row)" />
          <el-button :icon="Delete" circle type="danger" @click="remove(row)" />
        </template>
      </el-table-column>
    </el-table>
  </section>

  <el-dialog v-model="dialogVisible" :title="editingKey ? '编辑项目' : '新增项目'" width="820px">
    <el-form label-position="top" class="project-form">
      <el-form-item label="项目名称"><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="客户/业主单位"><el-input v-model="form.customer" /></el-form-item>
      <el-form-item label="项目地区"><el-input v-model="form.region" /></el-form-item>
      <el-form-item label="所属大区"><el-input v-model="form.area" /></el-form-item>
      <el-form-item label="项目类型"><el-input v-model="form.project_type" /></el-form-item>
      <el-form-item label="项目阶段"><el-input v-model="form.phase" /></el-form-item>
      <el-form-item label="项目状态"><el-input v-model="form.status" /></el-form-item>
      <el-form-item label="合同状态"><el-input v-model="form.contract_status" /></el-form-item>
      <el-form-item label="合同金额"><el-input v-model="form.budget" /></el-form-item>
      <el-form-item label="已发生成本"><el-input v-model="form.incurred_cost" placeholder="例如：30万、120000" /></el-form-item>
      <el-form-item label="项目经理"><el-input v-model="form.manager" /></el-form-item>
      <el-form-item label="预投入日期"><el-input v-model="form.pre_start_date" /></el-form-item>
      <el-form-item label="预计验收"><el-input v-model="form.acceptance" /></el-form-item>
      <el-form-item label="项目背景" class="field-full"><el-input v-model="form.background" type="textarea" :rows="3" /></el-form-item>
      <el-form-item label="项目计划" class="field-full"><el-input v-model="form.plan" type="textarea" :rows="3" /></el-form-item>
      <el-form-item label="展示到驾驶舱"><el-switch v-model="form.dashboard" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
