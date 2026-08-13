<template>
  <div class="detail-container" v-loading="loading">
    <div v-if="detail" class="detail-content">
      <div class="detail-header">
        <h2>
          {{ detail.photo_id }}
          <el-tag v-if="isVideo" type="warning" size="small" effect="light" class="media-tag">视频</el-tag>
          <el-tag v-else-if="isAudio" type="info" size="small" effect="light" class="media-tag">音频</el-tag>
        </h2>
        <div class="header-actions">
          <el-button type="primary" :loading="saving" @click="saveEdit">保存修改</el-button>
          <el-button @click="refresh">刷新</el-button>
        </div>
      </div>

      <div class="detail-body">
        <div class="photo-panel" v-if="detail.has_photo_file">
          <div v-if="isVideo" class="video-preview-panel">
            <img
              class="video-poster"
              :src="previewUrl(detail.source_path)"
              :alt="detail.photo_id"
            />
            <div class="video-meta">
              <span v-if="videoDurationLabel">时长 {{ videoDurationLabel }}</span>
              <span v-if="videoSizeLabel">{{ videoSizeLabel }}</span>
            </div>
            <el-button type="primary" @click="openSource">用系统播放器打开</el-button>
          </div>
          <FaceEnrollPanel
            v-else
            :photo-id="detail.photo_id"
            :source-path="detail.source_path"
            :has-photo-file="detail.has_photo_file"
            @enrolled="refresh"
          />
        </div>

        <div class="edit-panel">
          <h3>编辑（写入 JSON + SQLite）</h3>
          <el-form label-width="88px" class="edit-form">
            <el-form-item label="人物">
              <el-select
                v-model="form.personIds"
                multiple
                filterable
                clearable
                placeholder="从人脸库选择（保存时替换整表 people）"
                style="width: 100%"
              >
                <el-option
                  v-for="person in registryPeople"
                  :key="person.person_id"
                  :label="`${person.name} (${person.person_id})`"
                  :value="person.person_id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="地址">
              <el-select
                v-model="form.location"
                filterable
                allow-create
                clearable
                default-first-option
                placeholder="选择或输入地址"
                style="width: 100%"
                @change="onLocationChange"
              >
                <el-option
                  v-for="item in locationItems"
                  :key="item.location"
                  :label="item.location"
                  :value="item.location"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="省/市/区">
              <div class="admin-row">
                <el-input v-model="form.province" placeholder="省" />
                <el-input v-model="form.city" placeholder="市" />
                <el-input v-model="form.district" placeholder="区" />
              </div>
            </el-form-item>
            <el-form-item label="详细地址">
              <el-input v-model="form.formattedAddress" placeholder="高德原文 / 手填" />
            </el-form-item>
            <el-form-item label="场景">
              <el-input v-model="form.scene" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="物体">
              <el-select
                v-model="form.objects"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="回车添加"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="动作">
              <el-select
                v-model="form.actions"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="回车添加"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="情绪">
              <el-select
                v-model="form.emotion"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="回车添加"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="标签">
              <el-select
                v-model="form.tags"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="回车添加"
                style="width: 100%"
              />
            </el-form-item>
            <p class="edit-hint">改人物 → manual_people；改地址 → manual_location；改场景标签 → manual_vision。对应 backfill 不会覆盖。</p>
          </el-form>

          <h3>JSON 预览</h3>
          <div class="json-tree">
            <JsonTreeNode :data="detail.data" />
          </div>
        </div>
      </div>

      <div class="quick-info">
        <h3>快速信息</h3>
        <el-row :gutter="20">
          <el-col :span="6">
            <el-card class="info-card">
              <div class="info-label">Schema 版本</div>
              <div class="info-value">{{ detail.data.schema_version }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card class="info-card">
              <div class="info-label">时间戳</div>
              <div class="info-value">{{ formatTime(detail.data.timestamp) }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card class="info-card">
              <div class="info-label">设备</div>
              <div class="info-value">{{ detail.data.device_id || '-' }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card class="info-card">
              <div class="info-label">手改标记</div>
              <div class="info-value">
                <el-tag v-if="detail.data.manual_people" type="warning" size="small">people</el-tag>
                <el-tag v-if="detail.data.manual_vision" type="warning" size="small">vision</el-tag>
                <el-tag v-if="detail.data.manual_location" type="warning" size="small">location</el-tag>
                <el-tag v-if="detail.data.manual_edit && !detail.data.manual_people && !detail.data.manual_vision && !detail.data.manual_location" type="info" size="small">manual_edit</el-tag>
                <span v-if="!detail.data.manual_edit && !detail.data.manual_location && !detail.data.manual_people && !detail.data.manual_vision">-</span>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </div>

      <div class="arrays-section">
        <div class="array-item">
          <h4>人物 (people)</h4>
          <el-table :data="detail.data.people || []" stripe size="small">
            <el-table-column prop="id" label="ID" width="100" />
            <el-table-column prop="name" label="姓名" width="100" />
            <el-table-column prop="confidence" label="置信度" width="100">
              <template #default="scope">
                {{ scope.row.confidence != null ? `${(scope.row.confidence * 100).toFixed(1)}%` : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="role" label="角色" width="80" />
            <el-table-column prop="match_method" label="匹配方式" width="100" />
            <el-table-column prop="age_at_photo.label" label="年龄" width="120" />
          </el-table>
        </div>
      </div>
    </div>

    <div v-else-if="!loading" class="error-state">
      <el-empty description="未找到数据" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import JsonTreeNode from './JsonTreeNode.vue'
import FaceEnrollPanel from './FaceEnrollPanel.vue'

const props = defineProps({
  photoId: {
    type: String,
    required: true,
  },
})

const loading = ref(false)
const saving = ref(false)
const detail = ref(null)

const isVideo = computed(() => (detail.value?.media_type || '') === 'video')
const isAudio = computed(() => (detail.value?.media_type || '') === 'audio')
const videoDurationLabel = computed(() => {
  const sec = detail.value?.data?.source?.duration_s
  if (sec == null || sec === '') return ''
  const n = Number(sec)
  if (!Number.isFinite(n)) return ''
  if (n < 60) return `${n.toFixed(1)}s`
  const m = Math.floor(n / 60)
  const s = Math.round(n % 60)
  return `${m}:${String(s).padStart(2, '0')}`
})
const videoSizeLabel = computed(() => {
  const src = detail.value?.data?.source || {}
  const w = src.width
  const h = src.height
  if (!w || !h) return ''
  return `${w}×${h}`
})

function previewUrl(path) {
  return `/api/preview?path=${encodeURIComponent(path)}&size=960`
}

async function openSource() {
  if (!detail.value?.source_path) return
  try {
    await axios.post('/api/open', { path: detail.value.source_path })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '打开失败')
  }
}
const registryPeople = ref([])
const locations = ref([])
const locationItems = ref([])
const form = reactive({
  personIds: [],
  location: '',
  province: '',
  city: '',
  district: '',
  formattedAddress: '',
  scene: '',
  objects: [],
  actions: [],
  emotion: [],
  tags: [],
})

function fillForm(data) {
  form.personIds = (data.people || []).map((p) => p.id).filter(Boolean)
  form.location = data.location || ''
  const admin = data.location_admin || {}
  form.province = admin.province || ''
  form.city = admin.city || ''
  form.district = admin.district || ''
  form.formattedAddress = admin.formatted_address || ''
  form.scene = data.scene || ''
  form.objects = [...(data.objects || [])]
  form.actions = [...(data.actions || [])]
  form.emotion = [...(data.emotion || [])]
  form.tags = [...(data.tags || [])]
}

function onLocationChange(loc) {
  if (!loc) {
    return
  }
  const item = locationItems.value.find((entry) => entry.location === loc)
  if (!item) {
    return
  }
  form.province = item.province || ''
  form.city = item.city || ''
  form.district = item.district || ''
  form.formattedAddress = item.formatted_address || item.location || ''
}

async function loadRegistryPeople() {
  try {
    const res = await axios.get('/api/face/registry')
    registryPeople.value = res.data.people || []
  } catch (error) {
    console.error('加载人物列表失败:', error)
    registryPeople.value = []
  }
}

async function loadLocations() {
  try {
    const res = await axios.get('/api/memory/locations')
    locations.value = res.data.locations || []
    locationItems.value = res.data.items || []
  } catch (error) {
    console.error('加载地址列表失败:', error)
    locations.value = []
    locationItems.value = []
  }
}

async function loadDetail() {
  if (!props.photoId) return
  loading.value = true
  try {
    const res = await axios.get('/api/memory/detail', {
      params: { photo_id: props.photoId },
    })
    detail.value = res.data
    fillForm(res.data.data || {})
  } catch (error) {
    console.error('加载详情失败:', error)
    detail.value = null
  } finally {
    loading.value = false
  }
}

async function saveEdit() {
  if (!detail.value) return
  saving.value = true
  try {
    const res = await axios.put('/api/memory/update', {
      photo_id: detail.value.photo_id,
      person_ids: form.personIds,
      location: form.location,
      province: form.province,
      city: form.city,
      district: form.district,
      formatted_address: form.formattedAddress,
      scene: form.scene,
      objects: form.objects,
      actions: form.actions,
      emotion: form.emotion,
      tags: form.tags,
    })
    detail.value = {
      ...detail.value,
      data: res.data.data,
    }
    fillForm(res.data.data)
    await loadLocations()
    ElMessage.success('已保存并同步索引')
  } catch (error) {
    const detail = error.response?.data?.detail
    const msg = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
        : (error.message || '保存失败')
    ElMessage.error(msg)
  } finally {
    saving.value = false
  }
}

function refresh() {
  loadDetail()
}

function formatTime(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return timestamp
  return date.toLocaleString('zh-CN')
}

watch(() => props.photoId, () => {
  loadDetail()
})

onMounted(() => {
  loadRegistryPeople()
  loadLocations()
  loadDetail()
})
</script>

<style scoped>
.detail-container {
  height: 100%;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-bottom: 24px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.detail-header h2 {
  margin: 0;
  font-size: 1.5rem;
  font-family: monospace;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.media-tag {
  font-family: system-ui, sans-serif;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.video-preview-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.video-poster {
  width: 100%;
  max-height: 420px;
  object-fit: contain;
  border-radius: 8px;
  background: var(--thumb-bg);
  border: 1px solid var(--border);
}

.video-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  color: var(--muted);
  font-size: 0.9rem;
}

.detail-body {
  display: grid;
  grid-template-columns: 350px 1fr;
  gap: 1.5rem;
  margin-bottom: 2rem;
}

.photo-panel h3,
.edit-panel h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.edit-form {
  margin-bottom: 1.5rem;
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
}

.admin-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0.5rem;
  width: 100%;
}

.edit-hint {
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
  line-height: 1.5;
}

.json-tree {
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1rem;
  background: var(--bg);
  font-family: monospace;
  font-size: 0.85rem;
}

.quick-info h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.info-card {
  text-align: center;
}

.info-label {
  font-size: 0.8rem;
  color: var(--muted);
  margin-bottom: 0.3rem;
}

.info-value {
  font-size: 1.1rem;
  font-weight: 600;
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  justify-content: center;
  align-items: center;
}

.arrays-section {
  margin-top: 2rem;
}

.array-item {
  margin-bottom: 1.5rem;
}

.array-item h4 {
  margin: 0 0 0.75rem;
  font-size: 0.9rem;
  color: var(--muted);
}

.error-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}

@media (max-width: 900px) {
  .detail-body {
    grid-template-columns: 1fr;
  }

  .photo-panel {
    order: 2;
  }

  .edit-panel {
    order: 1;
  }
}
</style>
