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
          <el-dropdown
            split-button
            type="default"
            @click="copyImage"
            @command="onCopyCommand"
          >
            {{ copyingImage ? '复制中…' : (isVideo ? '复制封面' : '复制照片') }}
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="image" :disabled="!canCopyImage || copyingImage">
                  {{ isVideo ? '复制视频封面到剪贴板' : '复制照片到剪贴板' }}
                </el-dropdown-item>
                <el-dropdown-item command="summary">复制文字摘要</el-dropdown-item>
                <el-dropdown-item command="json">复制完整 JSON</el-dropdown-item>
                <el-dropdown-item command="photo_id">复制 photo_id</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button
            plain
            :disabled="!canPrint"
            :loading="printing"
            @click="printPhoto"
          >
            打印
          </el-button>
          <el-button type="primary" :loading="saving" @click="saveEdit">保存修改</el-button>
          <el-button @click="refresh">刷新</el-button>
        </div>
      </div>

      <div class="detail-body">
        <div class="photo-panel" v-if="detail.has_photo_file">
          <div v-if="isVideo" class="video-preview-panel">
            <video
              ref="videoElRef"
              class="video-player"
              controls
              playsinline
              preload="metadata"
              :key="detail.source_path"
              :poster="previewUrl(detail.source_path)"
              :src="mediaUrl(detail.source_path)"
            >
              当前浏览器无法播放该视频
            </video>
            <div class="video-meta">
              <span v-if="videoDurationLabel">时长 {{ videoDurationLabel }}</span>
              <span v-if="videoSizeLabel">{{ videoSizeLabel }}</span>
            </div>
            <el-button link type="primary" @click="openSource">用系统播放器打开</el-button>
            <div v-if="hasTranscriptField" class="transcript-box" :class="{ muted: !transcriptDraft && transcriptEmpty }">
              <div class="transcript-label-row">
                <span class="transcript-label">字幕 / 转写</span>
                <el-tag v-if="transcriptConfirmed" type="success" size="small" effect="plain">已确认·进问答</el-tag>
                <el-tag v-else-if="transcriptDraft" type="warning" size="small" effect="plain">草稿·不进问答</el-tag>
                <el-tag v-else type="info" size="small" effect="plain">空草稿</el-tag>
              </div>
              <el-input
                v-model="transcriptEdit"
                type="textarea"
                :rows="5"
                placeholder="自动转写为草稿；改完可保存，确认后才进问答检索"
                class="transcript-input"
              />
              <div class="transcript-actions">
                <el-button size="small" :loading="savingTranscript" @click="saveTranscript(false)">
                  保存草稿
                </el-button>
                <el-button
                  type="primary"
                  size="small"
                  :disabled="!transcriptEdit.trim()"
                  :loading="savingTranscript"
                  @click="saveTranscript(true)"
                >
                  确认进问答
                </el-button>
                <el-button link type="primary" size="small" :disabled="!transcriptEdit.trim()" @click="copyTranscript">
                  复制
                </el-button>
              </div>
            </div>
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
            <el-form-item label="旁白">
              <el-input
                v-model="form.userNote"
                type="textarea"
                :rows="3"
                placeholder="人写旁白/配文（写入 user_note；非 AI scene）"
              />
              <p v-if="detail.data.manual_note" class="edit-hint inline">已标记 manual_note · vision backfill 不会覆盖</p>
            </el-form-item>
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
            <p class="edit-hint">改旁白 → manual_note；改人物 → manual_people；改地址 → manual_location；改场景标签 → manual_vision。对应 backfill 不会覆盖。</p>
          </el-form>

          <div class="json-preview-header">
            <h3>JSON 预览</h3>
            <el-button link type="primary" @click="copyJson">复制 JSON</el-button>
          </div>
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
                <el-tag v-if="detail.data.manual_note" type="warning" size="small">note</el-tag>
                <el-tag v-if="detail.data.manual_people" type="warning" size="small">people</el-tag>
                <el-tag v-if="detail.data.manual_vision" type="warning" size="small">vision</el-tag>
                <el-tag v-if="detail.data.manual_location" type="warning" size="small">location</el-tag>
                <el-tag v-if="detail.data.manual_transcript" type="warning" size="small">transcript</el-tag>
                <el-tag v-if="detail.data.manual_edit && !detail.data.manual_people && !detail.data.manual_vision && !detail.data.manual_location && !detail.data.manual_transcript && !detail.data.manual_note" type="info" size="small">manual_edit</el-tag>
                <span v-if="!detail.data.manual_edit && !detail.data.manual_location && !detail.data.manual_people && !detail.data.manual_vision && !detail.data.manual_transcript && !detail.data.manual_note">-</span>
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
const copyingImage = ref(false)
const printing = ref(false)
const savingTranscript = ref(false)
const transcriptEdit = ref('')
const detail = ref(null)
const videoElRef = ref(null)

const isVideo = computed(() => (detail.value?.media_type || '') === 'video')
const isAudio = computed(() => (detail.value?.media_type || '') === 'audio')
const canCopyImage = computed(() => {
  if (!detail.value?.has_photo_file || !detail.value?.source_path) return false
  if (isAudio.value) return false
  return true
})
const canPrint = computed(() => canCopyImage.value)
const hasTranscriptField = computed(() => {
  if (!isVideo.value && !isAudio.value) return false
  return !!detail.value?.data && ('transcript' in (detail.value.data || {}) || isVideo.value)
})
const transcriptStatus = computed(() => {
  const tr = detail.value?.data?.transcript
  if (!tr || typeof tr !== 'object') return 'draft'
  return String(tr.status || '').toLowerCase() === 'confirmed' ? 'confirmed' : 'draft'
})
const transcriptConfirmed = computed(() => transcriptStatus.value === 'confirmed')
const transcriptDraft = computed(() => {
  const tr = detail.value?.data?.transcript
  if (!tr || typeof tr !== 'object') return false
  return !!String(tr.text || '').trim() && transcriptStatus.value !== 'confirmed'
})
const transcriptEmpty = computed(() => {
  const tr = detail.value?.data?.transcript
  if (!tr || typeof tr !== 'object') return false
  return !String(tr.text || '').trim()
})
const transcriptText = computed(() => transcriptEdit.value.trim())
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

function mediaUrl(path) {
  return `/api/media?path=${encodeURIComponent(path)}`
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
  userNote: '',
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
  // 用 in 判断：旧 Desk 忽略 user_note 时回包无此键，勿把编辑框清空
  if (Object.prototype.hasOwnProperty.call(data, 'user_note')) {
    form.userNote = data.user_note || ''
  }
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
    form.userNote = ''
    fillForm(res.data.data || {})
    const tr = res.data?.data?.transcript
    transcriptEdit.value = tr && typeof tr === 'object' ? String(tr.text || '') : ''
  } catch (error) {
    console.error('加载详情失败:', error)
    detail.value = null
    transcriptEdit.value = ''
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
      user_note: form.userNote,
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

function personNames() {
  const byId = new Map(registryPeople.value.map((p) => [p.person_id, p.name]))
  const fromData = new Map(
    (detail.value?.data?.people || []).map((p) => [p.id, p.name]).filter(([id]) => id),
  )
  return form.personIds
    .map((id) => byId.get(id) || fromData.get(id) || id)
    .filter(Boolean)
}

function buildSummaryText() {
  const data = detail.value?.data || {}
  const admin = [form.province, form.city, form.district].filter(Boolean).join(' / ')
  const lines = [
    `照片：${detail.value?.photo_id || ''}`,
    `时间：${formatTime(data.timestamp)}`,
    `地点：${form.location || '-'}`,
  ]
  if (admin) lines.push(`省市区：${admin}`)
  if (form.formattedAddress) lines.push(`详细地址：${form.formattedAddress}`)
  const people = personNames()
  lines.push(`人物：${people.length ? people.join('、') : '-'}`)
  lines.push(`旁白：${form.userNote || '-'}`)
  lines.push(`场景：${form.scene || '-'}`)
  lines.push(`物体：${form.objects.length ? form.objects.join('、') : '-'}`)
  lines.push(`动作：${form.actions.length ? form.actions.join('、') : '-'}`)
  lines.push(`情绪：${form.emotion.length ? form.emotion.join('、') : '-'}`)
  lines.push(`标签：${form.tags.length ? form.tags.join('、') : '-'}`)
  return lines.join('\n')
}

async function writeClipboard(text, successMsg) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const el = document.createElement('textarea')
      el.value = text
      el.setAttribute('readonly', '')
      el.style.position = 'fixed'
      el.style.left = '-9999px'
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
    }
    ElMessage.success(successMsg)
  } catch (error) {
    console.error('复制失败:', error)
    ElMessage.error('复制失败，请手动选择文本')
  }
}

function blobToPng(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const img = new Image()
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = img.naturalWidth || img.width
        canvas.height = img.naturalHeight || img.height
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          reject(new Error('canvas unavailable'))
          return
        }
        ctx.drawImage(img, 0, 0)
        canvas.toBlob(
          (png) => {
            URL.revokeObjectURL(url)
            if (!png) reject(new Error('toBlob failed'))
            else resolve(png)
          },
          'image/png',
        )
      } catch (error) {
        URL.revokeObjectURL(url)
        reject(error)
      }
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('image decode failed'))
    }
    img.src = url
  })
}

function canvasToPngBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (png) => {
        if (!png) reject(new Error('toBlob failed'))
        else resolve(png)
      },
      'image/png',
    )
  })
}

/** 从页内 <video> 截当前帧（同源 /api/media，无跨域污染） */
async function captureVideoFramePng() {
  const video = videoElRef.value
  if (!video) return null
  const w = video.videoWidth
  const h = video.videoHeight
  if (!w || !h) return null
  const canvas = document.createElement('canvas')
  // 最长边约 1024，避免超大帧
  const scale = Math.min(1, 1024 / Math.max(w, h))
  canvas.width = Math.max(1, Math.round(w * scale))
  canvas.height = Math.max(1, Math.round(h * scale))
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvasToPngBlob(canvas)
}

async function fetchPreviewPng(path) {
  const res = await fetch(`/api/preview?path=${encodeURIComponent(path)}&size=1024`)
  if (!res.ok) throw new Error(res.statusText || 'preview failed')
  const blob = await res.blob()
  const type = blob.type || ''
  if (type && !type.startsWith('image/')) {
    throw new Error('not an image')
  }
  return type === 'image/png' ? blob : blobToPng(blob)
}

async function resolveCopyPngBlob() {
  const path = detail.value?.source_path
  if (!path) throw new Error('no source')
  if (isVideo.value) {
    try {
      return await fetchPreviewPng(path)
    } catch (error) {
      console.warn('封面预览失败，尝试页内截帧:', error)
      const frame = await captureVideoFramePng()
      if (frame) return frame
      throw error
    }
  }
  return fetchPreviewPng(path)
}

async function copyImage() {
  if (copyingImage.value) return
  if (!canCopyImage.value) {
    ElMessage.warning(isAudio.value ? '音频无法复制为图片' : '没有可复制的图片文件')
    return
  }
  if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') {
    ElMessage.error('当前浏览器不支持复制图片到剪贴板')
    return
  }

  copyingImage.value = true
  // 必须在点击同步路径里创建 ClipboardItem；异步内容用 Promise，
  // 否则视频抽帧较慢时用户手势过期，clipboard.write 会失败。
  const pngPromise = resolveCopyPngBlob()
  try {
    await navigator.clipboard.write([
      new ClipboardItem({ 'image/png': pngPromise }),
    ])
    ElMessage.success(isVideo.value ? '已复制视频封面/当前帧，可粘贴到豆包' : '已复制照片，可直接粘贴到豆包')
  } catch (error) {
    console.error('复制失败:', error)
    try {
      // 部分浏览器不接受 Promise 型 ClipboardItem，再试一次已就绪的 Blob
      const pngBlob = await pngPromise
      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': pngBlob }),
      ])
      ElMessage.success(isVideo.value ? '已复制视频封面/当前帧，可粘贴到豆包' : '已复制照片，可直接粘贴到豆包')
    } catch (error2) {
      console.error('复制照片失败:', error2)
      ElMessage.error(
        isVideo.value
          ? '复制视频封面失败（可先点一下播放再复制；需 HTTPS/localhost）'
          : '复制照片失败（需 HTTPS/localhost，且浏览器支持图片剪贴板）',
      )
    }
  } finally {
    copyingImage.value = false
  }
}

async function copySummary() {
  if (!detail.value) return
  await writeClipboard(buildSummaryText(), '已复制摘要')
}

async function copyJson() {
  if (!detail.value?.data) return
  await writeClipboard(JSON.stringify(detail.value.data, null, 2), '已复制 JSON')
}

async function copyPhotoId() {
  if (!detail.value?.photo_id) return
  await writeClipboard(detail.value.photo_id, '已复制 photo_id')
}

async function copyTranscript() {
  if (!transcriptEdit.value.trim()) return
  await writeClipboard(transcriptEdit.value.trim(), '已复制字幕')
}

async function saveTranscript(confirm) {
  if (!detail.value?.photo_id) return
  if (confirm && !transcriptEdit.value.trim()) {
    ElMessage.warning('确认进问答前请填写字幕')
    return
  }
  savingTranscript.value = true
  try {
    const res = await axios.put('/api/memory/transcript', {
      photo_id: detail.value.photo_id,
      text: transcriptEdit.value,
      confirm: !!confirm,
    })
    detail.value = {
      ...detail.value,
      data: res.data.data,
    }
    const tr = res.data.transcript || res.data.data?.transcript
    transcriptEdit.value = tr && typeof tr === 'object' ? String(tr.text || '') : transcriptEdit.value
    ElMessage.success(confirm ? '已确认，字幕进入问答检索' : '草稿已保存（不进问答）')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存字幕失败')
  } finally {
    savingTranscript.value = false
  }
}

function onCopyCommand(command) {
  if (command === 'image') copyImage()
  else if (command === 'summary') copySummary()
  else if (command === 'json') copyJson()
  else if (command === 'photo_id') copyPhotoId()
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function printCaptionLines() {
  const data = detail.value?.data || {}
  const lines = []
  const ts = formatTime(data.timestamp)
  if (ts && ts !== '-') lines.push(ts)
  if (form.location) lines.push(form.location)
  const people = personNames()
  if (people.length) lines.push(people.join('、'))
  if (form.userNote.trim()) lines.push(form.userNote.trim())
  return lines
}

async function printPhoto() {
  if (!canPrint.value || printing.value) return
  const path = detail.value?.source_path
  if (!path) return

  printing.value = true
  let iframe = null
  try {
    const imgUrl = `/api/preview?path=${encodeURIComponent(path)}&size=0`
    const captionHtml = printCaptionLines()
      .map((line) => `<div>${escapeHtml(line)}</div>`)
      .join('')
    const footer = captionHtml ? `<footer class="caption">${captionHtml}</footer>` : ''

    iframe = document.createElement('iframe')
    iframe.setAttribute('aria-hidden', 'true')
    Object.assign(iframe.style, {
      position: 'fixed',
      width: '0',
      height: '0',
      border: 'none',
      opacity: '0',
      pointerEvents: 'none',
    })
    document.body.appendChild(iframe)

    const doc = iframe.contentDocument
    const win = iframe.contentWindow
    if (!doc || !win) throw new Error('iframe unavailable')

    doc.open()
    doc.write(`<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>打印</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 12mm; font-family: system-ui, sans-serif; }
  .page {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    min-height: calc(100vh - 24mm); gap: 8mm;
  }
  img { max-width: 100%; max-height: 85vh; object-fit: contain; }
  .caption { text-align: center; font-size: 11pt; color: #333; line-height: 1.5; }
  @media print {
    body { padding: 0; }
    .page { min-height: auto; }
    img { max-height: none; page-break-inside: avoid; }
  }
</style></head>
<body><div class="page">
  <img src="${imgUrl.replace(/"/g, '&quot;')}" alt="" />
  ${footer}
</div></body></html>`)
    doc.close()

    const img = doc.querySelector('img')
    await new Promise((resolve, reject) => {
      if (!img) {
        reject(new Error('no img'))
        return
      }
      if (img.complete) resolve()
      else {
        img.onload = () => resolve()
        img.onerror = () => reject(new Error('image load failed'))
      }
    })

    const cleanup = () => {
      iframe?.remove()
      printing.value = false
    }
    win.onafterprint = cleanup
    win.focus()
    win.print()
    setTimeout(cleanup, 120000)
  } catch (error) {
    console.error('打印失败:', error)
    iframe?.remove()
    printing.value = false
    ElMessage.error('打印失败，请确认照片可预览')
  }
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

.video-player {
  width: 100%;
  max-height: 420px;
  border-radius: 8px;
  background: var(--thumb-bg);
  border: 1px solid var(--border);
  vertical-align: middle;
}

.video-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  color: var(--muted);
  font-size: 0.9rem;
}

.transcript-box {
  margin-top: 0.75rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
}

.transcript-box.muted {
  opacity: 0.85;
}

.transcript-label-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.transcript-label {
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.transcript-input {
  margin-bottom: 0.5rem;
}

.transcript-input :deep(textarea) {
  font-family: system-ui, sans-serif;
  font-size: 0.95rem;
  line-height: 1.55;
}

.transcript-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
}

.transcript-text {
  margin: 0 0 0.5rem;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: system-ui, sans-serif;
  font-size: 0.95rem;
  line-height: 1.55;
  max-height: 220px;
  overflow-y: auto;
}

.transcript-empty {
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
}

.detail-body {
  display: grid;
  grid-template-columns: 350px 1fr;
  gap: 1.5rem;
  margin-bottom: 2rem;
}

.detail-body:has(.video-preview-panel) {
  grid-template-columns: minmax(420px, 0.9fr) 1fr;
}

.photo-panel h3,
.edit-panel h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.json-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.json-preview-header h3 {
  margin: 0;
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

.edit-hint.inline {
  margin-top: 0.35rem;
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
