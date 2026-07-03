<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Download, Finished, MagicStick, UploadFilled, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { extractDocumentContent } from '@/api/documents'
import { useDocumentStore } from '@/stores/documents'
import { useProjectStore } from '@/stores/projects'

const templateTypeOptions = [
  { label: '需求规格说明书', value: 'srs' },
  { label: '产品需求文档 PRD', value: 'prd' },
  { label: '技术方案', value: 'technical_solution' },
  { label: '接口设计文档', value: 'api_design' },
  { label: '数据库设计文档', value: 'database_design' },
  { label: '测试方案', value: 'test_plan' },
  { label: '部署实施方案', value: 'deployment_plan' },
  { label: '运维手册', value: 'operation_manual' },
  { label: '用户使用手册', value: 'user_manual' },
  { label: '验收报告', value: 'acceptance_report' },
  { label: '项目周报', value: 'weekly' },
  { label: '会议纪要', value: 'meeting_minutes' },
]

const documentStore = useDocumentStore()
const projectStore = useProjectStore()
const templateFileInput = ref<HTMLInputElement | null>(null)
const contentFileInput = ref<HTMLInputElement | null>(null)
const uploadForm = reactive({
  name: '',
  template_type: 'srs',
  file: null as File | null,
})
const generateTitle = ref('')
const inputContent = ref('')
const contentFileName = ref('')
const previewVisible = ref(false)
const activeStep = ref(0)

const currentProjectKey = computed(() => projectStore.selectedProject?.key || '')
const selectedTemplate = computed(() => documentStore.selectedTemplate)
const selectedTemplateTypeLabel = computed(() => {
  const type = selectedTemplate.value?.template_type || uploadForm.template_type
  return templateTypeOptions.find((option) => option.value === type)?.label || type
})
const templateVariables = computed(() =>
  (selectedTemplate.value?.variables || '项目、任务、风险、需求、里程碑')
    .split(/[、,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean),
)

watch(currentProjectKey, (key) => {
  previewVisible.value = false
  documentStore.refresh(key)
})

watch(
  () => documentStore.selectedTemplateId,
  () => {
    previewVisible.value = false
    if (currentProjectKey.value) documentStore.refresh(currentProjectKey.value)
  },
)

watch(
  () => documentStore.selectedVersionId,
  () => {
    previewVisible.value = false
  },
)

onMounted(() => {
  if (currentProjectKey.value) documentStore.refresh(currentProjectKey.value)
})

function pickTemplateFile(event: Event) {
  const input = event.target as HTMLInputElement
  uploadForm.file = input.files?.[0] || null
  if (uploadForm.file && !uploadForm.name) {
    uploadForm.name = uploadForm.file.name.replace(/\.[^.]+$/, '')
  }
}

function triggerTemplateFileDialog() {
  templateFileInput.value?.click()
}

async function pickContentFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  contentFileName.value = file.name
  if (/\.docx$/i.test(file.name)) {
    try {
      const result = await extractDocumentContent(file)
      inputContent.value = result.content
      ElMessage.success('Word 内容已读取')
    } catch (err) {
      ElMessage.error(err instanceof Error ? `Word 内容读取失败：${err.message}` : 'Word 内容读取失败')
    }
    return
  }
  const isReadableText =
    file.type.startsWith('text/') || /\.(md|txt|json|csv|log)$/i.test(file.name)
  if (!isReadableText) {
    ElMessage.warning('当前支持读取 DOCX、Markdown、TXT、JSON、CSV 等文件内容')
    return
  }
  inputContent.value = await file.text()
  ElMessage.success('内容文件已读取')
}

function triggerContentFileDialog() {
  contentFileInput.value?.click()
}

async function uploadTemplate() {
  if (!uploadForm.name.trim()) {
    ElMessage.warning('请填写模板名称')
    return
  }
  if (!uploadForm.file) {
    ElMessage.warning('请选择模板文件')
    return
  }
  await documentStore.uploadTemplate(
    {
      name: uploadForm.name,
      template_type: uploadForm.template_type,
      file: uploadForm.file,
    },
    currentProjectKey.value,
  )
  uploadForm.name = ''
  uploadForm.file = null
  if (templateFileInput.value) templateFileInput.value.value = ''
  ElMessage.success('模板已上传并选中')
}

async function deleteTemplate(templateId: number, templateName: string) {
  try {
    await ElMessageBox.confirm(
      `确认删除“${templateName}”？关联的生成历史也会一并清理。`,
      '删除模板',
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
  await documentStore.deleteTemplate(templateId, currentProjectKey.value)
  previewVisible.value = false
  ElMessage.success('模板已删除')
}

async function generateDocument() {
  if (!currentProjectKey.value) {
    ElMessage.warning('请选择项目')
    return
  }
  if (!documentStore.selectedTemplate?.id) {
    ElMessage.warning('请先选择或上传模板')
    return
  }
  await documentStore.generate(currentProjectKey.value, generateTitle.value || undefined, inputContent.value)
  previewVisible.value = false
  ElMessage.success('文档已生成，可点击预览查看结果')
}

function showPreview() {
  if (!documentStore.selectedVersion) {
    ElMessage.warning('请先生成文档')
    return
  }
  previewVisible.value = true
}

async function exportWord() {
  await documentStore.exportWord(currentProjectKey.value)
  ElMessage.success('Word 已导出')
}

function goNext() {
  if (activeStep.value === 0 && !documentStore.selectedTemplate?.id) {
    ElMessage.warning('请先选择或上传模板')
    return
  }
  activeStep.value = Math.min(activeStep.value + 1, 3)
}

function goPrev() {
  activeStep.value = Math.max(activeStep.value - 1, 0)
}

function finishDocumentWorkflow() {
  if (!documentStore.selectedVersion) {
    ElMessage.warning('请先生成文档')
    return
  }
  activeStep.value = 0
  previewVisible.value = false
  ElMessage.success('智能文档流程已完成')
}
</script>

<template>
  <section class="doc-flow">
    <div class="panel doc-wizard-panel">
      <el-steps :active="activeStep" finish-status="success" process-status="process" align-center>
        <el-step title="选择模板" />
        <el-step title="查看变量" />
        <el-step title="录入内容" />
        <el-step title="生成导出" />
      </el-steps>

      <div class="doc-step-body">
        <div v-if="activeStep === 0">
          <div class="doc-step-head">
            <span>1</span>
            <div>
              <h3>选择模板或上传模板</h3>
              <p>先确定要套用的交付文档类型和模板资产。</p>
            </div>
          </div>

          <div class="doc-template-grid">
            <el-form label-position="top" class="doc-template-select">
              <el-form-item label="项目上下文">
                <el-select v-model="projectStore.selectedKey" placeholder="选择项目">
                  <el-option
                    v-for="project in projectStore.projects"
                    :key="project.key"
                    :label="project.name"
                    :value="project.key"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="已有模板">
                <el-select v-model="documentStore.selectedTemplateId" placeholder="选择模板">
                  <el-option
                    v-for="template in documentStore.templates"
                    :key="template.id"
                    :label="template.name"
                    :value="template.id"
                  >
                    <div class="template-option-row">
                      <span class="template-option-name">{{ template.name }}</span>
                      <el-button
                        class="template-delete-button"
                        text
                        type="danger"
                        :icon="Delete"
                        :aria-label="`删除模板 ${template.name}`"
                        title="删除模板"
                        @mousedown.stop.prevent
                        @click.stop.prevent="deleteTemplate(template.id, template.name)"
                      />
                    </div>
                  </el-option>
                </el-select>
              </el-form-item>
            </el-form>

            <el-form label-position="top" class="docs-upload-form">
              <el-form-item label="新模板名称">
                <el-input v-model="uploadForm.name" placeholder="例如：接口设计文档模板" />
              </el-form-item>
              <el-form-item label="新模板类型">
                <el-select v-model="uploadForm.template_type">
                  <el-option
                    v-for="option in templateTypeOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="模板文件" class="field-full">
                <input
                  id="template-file-input"
                  ref="templateFileInput"
                  class="file-input-hidden"
                  type="file"
                  accept=".doc,.docx,.ppt,.pptx,.md,.txt,.pdf"
                  @change="pickTemplateFile"
                />
                <label class="file-picker-button primary" for="template-file-input" data-testid="choose-template-file-button">
                  <el-icon><UploadFilled /></el-icon>
                  <span>选择模板文件</span>
                </label>
                <span class="file-name">{{ uploadForm.file?.name || '未选择模板文件' }}</span>
              </el-form-item>
              <el-button type="primary" data-testid="upload-template-button" :icon="UploadFilled" @click="uploadTemplate">上传并选中模板</el-button>
            </el-form>
          </div>
        </div>

        <div v-else-if="activeStep === 1">
          <div class="doc-step-head">
            <span>2</span>
            <div>
              <h3>查看模板变量信息</h3>
              <p>确认模板将读取哪些项目上下文和交付内容。</p>
            </div>
          </div>
          <div v-if="selectedTemplate" class="template-summary">
            <div>
              <strong>{{ selectedTemplate.name }}</strong>
              <small>{{ selectedTemplateTypeLabel }} · {{ selectedTemplate.original_filename || '无文件名' }}</small>
            </div>
            <div class="variable-chips">
              <el-tag v-for="variable in templateVariables" :key="variable" type="info">{{ variable }}</el-tag>
            </div>
          </div>
          <el-empty v-else description="请先选择或上传模板" :image-size="80" />
        </div>

        <div v-else-if="activeStep === 2">
          <div class="doc-step-head">
            <span>3</span>
            <div>
              <h3>录入或上传要转化的内容</h3>
              <p>这里填写本次要套入模板的新内容，系统会结合项目上下文生成文档。</p>
            </div>
          </div>

          <el-form label-position="top" class="doc-compose-form">
            <el-form-item label="文档标题">
              <el-input v-model="generateTitle" placeholder="可选：不填则使用项目名 + 模板类型" />
            </el-form-item>
            <el-form-item label="内容文件">
              <input
                id="content-file-input"
                ref="contentFileInput"
                class="file-input-hidden"
                type="file"
                accept=".docx,.md,.txt,.json,.csv,.log,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/markdown,text/plain,application/json,text/csv"
                @change="pickContentFile"
              />
              <label class="file-picker-button primary" for="content-file-input" data-testid="upload-content-file-button">
                <el-icon><UploadFilled /></el-icon>
                <span>上传内容文件</span>
              </label>
              <span class="file-name">{{ contentFileName || '未上传内容文件，可直接在下方输入' }}</span>
            </el-form-item>
            <el-form-item label="内容输入">
              <div data-testid="doc-content-input">
                <el-input
                  v-model="inputContent"
                  type="textarea"
                  :rows="9"
                  placeholder="输入会议结论、接口清单、测试范围、部署步骤、验收口径等需要转化为模板文档的内容。"
                />
              </div>
            </el-form-item>
          </el-form>
        </div>

        <div v-else>
          <div class="doc-step-head">
            <span>4</span>
            <div>
              <h3>生成、预览和导出</h3>
              <p>先生成草稿，再预览结果，确认无误后导出 Word。</p>
            </div>
          </div>

          <div class="doc-action-bar">
            <el-button type="primary" data-testid="generate-document-button" :loading="documentStore.generating" :icon="MagicStick" @click="generateDocument">
              生成文档
            </el-button>
            <el-button data-testid="preview-document-button" :icon="View" :disabled="!documentStore.selectedVersion" @click="showPreview">预览生成结果</el-button>
            <el-button data-testid="export-word-button" :loading="documentStore.exporting" :icon="Download" :disabled="!documentStore.selectedVersion" @click="exportWord">
              导出 Word
            </el-button>
          </div>

          <article v-if="previewVisible && documentStore.selectedVersion" class="doc-preview" v-html="documentStore.selectedVersion.content_html" />
          <el-empty v-else description="生成后点击预览生成结果" :image-size="96" />

          <div class="doc-history-inline">
            <div class="panel-head">
              <h3>生成历史</h3>
              <el-tag>{{ documentStore.versions.length }} 个版本</el-tag>
            </div>
            <div class="version-list">
              <button
                v-for="version in documentStore.versions"
                :key="version.id"
                class="version-card"
                :class="{ active: documentStore.selectedVersionId === version.id }"
                @click="documentStore.selectedVersionId = version.id"
              >
                <strong>{{ version.title }}</strong>
                <span>V{{ version.version }} · {{ version.created_at }}</span>
                <small>Word：{{ version.word_status }} · PDF：{{ version.pdf_status }} · 飞书：{{ version.lark_status }}</small>
                <a v-if="version.export_url" :href="version.export_url" target="_blank" @click.stop>打开 Word</a>
              </button>
              <el-empty v-if="documentStore.versions.length === 0" description="暂无生成历史" :image-size="80" />
            </div>
          </div>
        </div>
      </div>

      <div class="doc-step-footer">
        <el-button data-testid="doc-prev-button" :disabled="activeStep === 0" @click="goPrev">上一步</el-button>
        <el-button v-if="activeStep < 3" data-testid="doc-next-button" type="primary" @click="goNext">下一步</el-button>
        <el-button v-else data-testid="finish-doc-button" type="primary" :icon="Finished" @click="finishDocumentWorkflow">完成</el-button>
      </div>
    </div>
  </section>
</template>
