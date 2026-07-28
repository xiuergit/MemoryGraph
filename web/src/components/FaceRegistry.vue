<template>
  <div class="registry-container">
    <div class="registry-header">
      <p class="intro">
        管理人脸库成员：编辑中文名 / 角色 / 生日 / 识别阈值，删除参考照。保存或删图后会自动重建
        <code>index.json</code>。
      </p>
      <div v-if="globalDefault != null" class="config-bar">
        <el-tag type="info">全局默认阈值 {{ globalDefault }}</el-tag>
        <el-button size="small" :loading="rebuilding" @click="rebuildIndex">
          重建 index
        </el-button>
        <el-button size="small" @click="loadPeople">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="20" class="registry-body">
      <el-col :span="10" :xs="24" class="list-col">
        <el-table
          v-loading="loadingList"
          :data="people"
          stripe
          highlight-current-row
          height="100%"
          class="people-table"
          @current-change="onSelectPerson"
        >
          <el-table-column label="中文名" min-width="100">
            <template #default="scope">
              <span class="name-cell">{{ scope.row.name }}</span>
              <span class="id-cell">{{ scope.row.person_id }}</span>
            </template>
          </el-table-column>
          <el-table-column label="参考照" width="72" align="center">
            <template #default="scope">{{ scope.row.ref_count }}</template>
          </el-table-column>
          <el-table-column label="阈值" width="72" align="center">
            <template #default="scope">
              {{ formatThreshold(scope.row.effective_threshold) }}
            </template>
          </el-table-column>
        </el-table>
      </el-col>

      <el-col :span="14" :xs="24" class="detail-col">
        <div v-if="!selectedId" class="empty-detail">
          <el-empty description="左侧选择一位成员" />
        </div>

        <div v-else v-loading="loadingDetail" class="detail-panel">
          <h3 class="detail-title">
            {{ detail.name || selectedId }}
            <span class="detail-id">{{ selectedId }}</span>
          </h3>

          <el-form label-width="96px" class="edit-form" @submit.prevent>
            <el-form-item label="中文名">
              <el-input v-model="form.name" />
            </el-form-item>
            <el-form-item label="角色">
              <el-select v-model="form.role" style="width: 100%">
                <el-option label="孩子 child" value="child" />
                <el-option label="家长 parent" value="parent" />
                <el-option label="亲戚长辈 relative" value="relative" />
                <el-option label="兄弟姐妹 sibling" value="sibling" />
                <el-option label="朋友 friend" value="friend" />
                <el-option label="其他 other" value="other" />
              </el-select>
            </el-form-item>
            <el-form-item label="生日">
              <el-input v-model="form.birth_date" placeholder="YYYY-MM-DD" />
            </el-form-item>
            <el-form-item label="识别阈值">
              <el-input-number
                v-model="form.match_threshold"
                :min="0.01"
                :max="1"
                :step="0.05"
                :precision="2"
                controls-position="right"
                class="threshold-input"
              />
              <el-checkbox v-model="useGlobalThreshold" class="global-check">
                使用全局默认（{{ globalDefault ?? '-' }}）
              </el-checkbox>
              <div class="field-hint">
                宝宝等变化大的人可设低一些（如 0.55）；成人可设高一些（如 0.70）减少误认。
              </div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="savePerson">
                保存属性
              </el-button>
            </el-form-item>
          </el-form>

          <div class="refs-section">
            <div class="refs-header">
              <h4>参考照（{{ detail.refs?.length || 0 }}）</h4>
            </div>
            <p v-if="!(detail.refs?.length)" class="hint muted">暂无参考照</p>
            <div v-else class="refs-grid">
              <div
                v-for="ref in detail.refs"
                :key="ref.file"
                class="ref-card"
              >
                <img
                  :src="previewUrl(ref.preview_path)"
                  :alt="ref.name"
                  class="ref-thumb"
                  loading="lazy"
                />
                <div class="ref-meta">
                  <span class="ref-name" :title="ref.name">{{ ref.name }}</span>
                  <el-button
                    link
                    type="danger"
                    size="small"
                    :loading="deletingRef === ref.file"
                    @click="deleteRef(ref)"
                  >
                    删除
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const people = ref([])
const loadingList = ref(false)
const loadingDetail = ref(false)
const saving = ref(false)
const rebuilding = ref(false)
const deletingRef = ref('')
const selectedId = ref('')
const detail = ref({})
const globalDefault = ref(null)
const useGlobalThreshold = ref(true)

const form = ref({
  name: '',
  role: 'other',
  birth_date: '',
  match_threshold: 0.55,
})

function formatThreshold(value) {
  if (value == null) return '-'
  return Number(value).toFixed(2)
}

function previewUrl(path) {
  if (!path) return ''
  return `/api/preview?path=${encodeURIComponent(path)}`
}

async function loadPeople() {
  loadingList.value = true
  try {
    const res = await axios.get('/api/face/people')
    people.value = res.data.people || []
    if (selectedId.value && !people.value.find((p) => p.person_id === selectedId.value)) {
      selectedId.value = ''
      detail.value = {}
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载人脸库失败')
  } finally {
    loadingList.value = false
  }
}

async function loadDetail(personId) {
  if (!personId) return
  loadingDetail.value = true
  try {
    const res = await axios.get(`/api/face/people/${encodeURIComponent(personId)}`)
    detail.value = res.data
    globalDefault.value = res.data.global_default_threshold ?? globalDefault.value
    form.value = {
      name: res.data.name || personId,
      role: res.data.role || 'other',
      birth_date: res.data.birth_date || '',
      match_threshold: res.data.match_threshold ?? res.data.effective_threshold ?? 0.55,
    }
    useGlobalThreshold.value = res.data.match_threshold == null
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载成员详情失败')
  } finally {
    loadingDetail.value = false
  }
}

function onSelectPerson(row) {
  if (!row) return
  selectedId.value = row.person_id
  loadDetail(row.person_id)
}

async function savePerson() {
  if (!selectedId.value) return
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      role: form.value.role,
      birth_date: form.value.birth_date.trim(),
      match_threshold: useGlobalThreshold.value ? null : form.value.match_threshold,
    }
    const res = await axios.put(
      `/api/face/people/${encodeURIComponent(selectedId.value)}`,
      payload,
    )
    detail.value = res.data
    ElMessage.success('已保存并重建 index')
    await loadPeople()
  } catch (error) {
    const detail = error.response?.data?.detail
    const msg = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
        : (detail ? JSON.stringify(detail) : error.message || '保存失败')
    ElMessage.error(msg)
  } finally {
    saving.value = false
  }
}

async function deleteRef(ref) {
  if (!selectedId.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除参考照「${ref.name}」？删除后会重建 index.json。`,
      '删除参考照',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  deletingRef.value = ref.file
  try {
    const res = await axios.delete(
      `/api/face/people/${encodeURIComponent(selectedId.value)}/refs`,
      { params: { file: ref.file } },
    )
    detail.value = res.data
    ElMessage.success('已删除参考照')
    await loadPeople()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '删除失败')
  } finally {
    deletingRef.value = ''
  }
}

async function rebuildIndex() {
  rebuilding.value = true
  try {
    const res = await axios.post('/api/face/rebuild-index')
    ElMessage.success(`已重建 index（${res.data.people_count} 人）`)
    if (selectedId.value) await loadDetail(selectedId.value)
    await loadPeople()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重建失败')
  } finally {
    rebuilding.value = false
  }
}

watch(useGlobalThreshold, (useGlobal) => {
  if (!useGlobal && form.value.match_threshold == null) {
    form.value.match_threshold = globalDefault.value ?? 0.55
  }
})

onMounted(() => {
  loadPeople()
})
</script>

<style scoped>
.registry-container {
  max-width: 1200px;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.registry-header {
  flex-shrink: 0;
}

.intro {
  margin: 0 0 0.75rem;
  color: var(--muted);
  font-size: 0.9rem;
}

.config-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.registry-body {
  flex: 1;
  min-height: 0;
  height: 0; /* flex 子项可收缩，才能把高度传给表格 */
  margin-top: 0;
  align-items: stretch;
}

.registry-body :deep(.el-col) {
  height: 100%;
  min-height: 0;
  max-height: 100%;
}

.list-col,
.detail-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  max-height: 100%;
}

@media (max-width: 767px) {
  .registry-container {
    overflow-y: auto;
  }

  .registry-body {
    height: auto;
    flex: none;
  }

  .registry-body :deep(.el-col) {
    height: auto;
    max-height: none;
  }

  .people-table {
    height: 420px !important;
  }

  .detail-panel,
  .empty-detail {
    max-height: none;
    overflow: visible;
  }
}

.people-table {
  width: 100%;
  flex: 1;
  min-height: 0;
}

.name-cell {
  display: block;
  font-weight: 500;
}

.id-cell {
  display: block;
  font-size: 0.75rem;
  color: var(--muted);
}

.empty-detail {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 0;
  border: 1px dashed var(--border);
  border-radius: 10px;
}

.detail-panel {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1rem 1.25rem;
  background: var(--panel);
}

.detail-title {
  margin: 0 0 1rem;
  font-size: 1.1rem;
}

.detail-id {
  margin-left: 0.5rem;
  font-size: 0.85rem;
  color: var(--muted);
  font-weight: normal;
}

.threshold-input {
  width: 140px;
  margin-right: 0.75rem;
}

.global-check {
  vertical-align: middle;
}

.field-hint {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.35rem;
  line-height: 1.4;
}

.refs-section {
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
}

.refs-header h4 {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
  color: var(--muted);
}

.refs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 0.75rem;
}

.ref-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg, #111);
}

.ref-thumb {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
}

.ref-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.25rem;
  padding: 0.35rem 0.5rem;
  font-size: 0.75rem;
}

.ref-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.hint.muted {
  color: var(--muted);
  font-size: 0.85rem;
}
</style>
