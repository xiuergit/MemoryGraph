<template>
  <div class="face-enroll-panel">
    <div class="panel-header">
      <h3>人脸库</h3>
      <el-button size="small" :loading="detecting" @click="detectFaces">
        {{ faces.length ? '重新检测' : '检测人脸' }}
      </el-button>
    </div>

    <p v-if="!hasPhotoFile" class="hint muted">无原图，无法入库</p>
    <p v-else-if="detectError" class="hint error">{{ detectError }}</p>
    <p v-else-if="detected && faces.length === 0" class="hint muted">未检测到人脸</p>

    <div v-if="hasPhotoFile && sourcePath" class="photo-stage">
      <div class="photo-wrap" ref="photoWrapRef">
        <img
          ref="photoImgRef"
          :src="previewUrl"
          alt="face detect"
          class="stage-image"
          @load="updateDisplaySize"
        />
        <button
          v-for="face in faces"
          :key="face.index"
          type="button"
          class="face-box"
          :class="{
            selected: selectedIndex === face.index,
            disabled: face.enrollable === false,
          }"
          :style="boxStyle(face.bbox)"
          :title="faceTitle(face)"
          @click="selectFace(face)"
        >
          <span class="face-label">{{ face.index + 1 }}</span>
        </button>
      </div>
      <p class="hint">点击人脸框选中，再点「加入人脸库」。灰色框质量不足，不能入库。</p>
    </div>

    <el-table
      v-if="faces.length"
      :data="faces"
      size="small"
      stripe
      class="face-table"
      highlight-current-row
      @current-change="onTableSelect"
    >
      <el-table-column label="#" width="48">
        <template #default="scope">{{ scope.row.index + 1 }}</template>
      </el-table-column>
      <el-table-column label="检测分" width="72">
        <template #default="scope">
          {{ scope.row.det_score != null ? scope.row.det_score.toFixed(2) : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="库内匹配" min-width="120">
        <template #default="scope">
          <span v-if="scope.row.matched">
            {{ scope.row.matched.name }}
            ({{ (scope.row.matched.confidence * 100).toFixed(0) }}%)
          </span>
          <span v-else class="muted">未识别</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="scope">
          <el-button
            v-if="scope.row.enrollable !== false"
            link
            type="primary"
            @click="openEnroll(scope.row)"
          >
            入库
          </el-button>
          <span v-else class="muted" :title="scope.row.enroll_skip_reason || ''">不可入库</span>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="hasPhotoFile && faces.length" class="actions">
      <el-button
        type="primary"
        :disabled="!canEnrollSelected"
        @click="openEnroll(selectedFace)"
      >
        加入人脸库
      </el-button>
    </div>

    <el-dialog
      v-model="dialogVisible"
      title="加入人脸库"
      width="480px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="选中人脸">
          <span>#{{ enrollFaceIndex !== null ? enrollFaceIndex + 1 : '-' }}</span>
        </el-form-item>
        <el-form-item label="成员">
          <el-radio-group v-model="memberMode">
            <el-radio value="existing">追加到已有</el-radio>
            <el-radio value="new">新建成员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="memberMode === 'existing'" label="选择">
          <el-select
            v-model="form.person_id"
            filterable
            placeholder="选择 person_id"
            style="width: 100%"
            @change="onExistingPick"
          >
            <el-option
              v-for="p in registryPeople"
              :key="p.person_id"
              :label="`${p.name} (${p.person_id})`"
              :value="p.person_id"
            />
          </el-select>
        </el-form-item>
        <template v-else>
          <el-form-item label="person_id" required>
            <el-input
              v-model="form.person_id"
              placeholder="小写英文，如 luoluo"
            />
            <div class="field-hint">字母开头，仅 a-z、0-9、_</div>
          </el-form-item>
          <el-form-item label="中文名" required>
            <el-input v-model="form.name" placeholder="如 落落" />
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
            <el-input v-model="form.birth_date" placeholder="YYYY-MM-DD，可选" />
          </el-form-item>
          <el-form-item label="识别阈值">
            <el-input-number
              v-model="form.match_threshold"
              :min="0.01"
              :max="1"
              :step="0.05"
              :precision="2"
              controls-position="right"
              :disabled="form.use_global_threshold"
            />
            <el-checkbox v-model="form.use_global_threshold" class="threshold-check">
              使用全局默认
            </el-checkbox>
          </el-form-item>
        </template>
        <el-form-item label="入库后">
          <el-checkbox v-model="form.reidentify_photo">
            重识别本张照片并更新索引
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="enrolling" @click="submitEnroll">
          确认入库
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const props = defineProps({
  photoId: { type: String, required: true },
  sourcePath: { type: String, default: '' },
  hasPhotoFile: { type: Boolean, default: false },
})

const emit = defineEmits(['enrolled'])

const detecting = ref(false)
const detected = ref(false)
const detectError = ref('')
const faces = ref([])
const imageSize = ref({ width: 0, height: 0 })
const displaySize = ref({ width: 0, height: 0 })
const selectedIndex = ref(null)

const registryPeople = ref([])
const dialogVisible = ref(false)
const enrolling = ref(false)
const memberMode = ref('new')
const enrollFaceIndex = ref(null)

const form = ref({
  person_id: '',
  name: '',
  role: 'friend',
  birth_date: '',
  match_threshold: 0.55,
  use_global_threshold: true,
  reidentify_photo: true,
})

const photoWrapRef = ref(null)
const photoImgRef = ref(null)

const previewUrl = computed(() => {
  if (!props.sourcePath) return ''
  return `/api/preview?path=${encodeURIComponent(props.sourcePath)}`
})

const selectedFace = computed(() =>
  faces.value.find((f) => f.index === selectedIndex.value) || null,
)

const canEnrollSelected = computed(
  () => selectedFace.value != null && selectedFace.value.enrollable !== false,
)

function boxStyle(bbox) {
  if (!bbox || !imageSize.value.width || !displaySize.value.width) return {}
  const sx = displaySize.value.width / imageSize.value.width
  const sy = displaySize.value.height / imageSize.value.height
  const [x1, y1, x2, y2] = bbox
  return {
    left: `${x1 * sx}px`,
    top: `${y1 * sy}px`,
    width: `${(x2 - x1) * sx}px`,
    height: `${(y2 - y1) * sy}px`,
  }
}

function faceTitle(face) {
  if (face.enrollable === false) {
    return `#${face.index + 1} 不可入库：${face.enroll_skip_reason || '质量不足'}`
  }
  if (face.matched) {
    const score = face.det_score != null ? ` · 检测分 ${face.det_score.toFixed(2)}` : ''
    return `#${face.index + 1} 已匹配 ${face.matched.name}${score}`
  }
  const score = face.det_score != null ? ` · 检测分 ${face.det_score.toFixed(2)}` : ''
  return `#${face.index + 1} 可入库${score}`
}

function updateDisplaySize() {
  const img = photoImgRef.value
  if (!img) return
  displaySize.value = {
    width: img.clientWidth,
    height: img.clientHeight,
  }
}

async function loadRegistry() {
  try {
    const res = await axios.get('/api/face/registry')
    registryPeople.value = res.data.people || []
  } catch (error) {
    console.error('加载 registry 失败:', error)
  }
}

async function detectFaces() {
  if (!props.hasPhotoFile || !props.photoId) return
  detecting.value = true
  detectError.value = ''
  try {
    const res = await axios.get('/api/face/detect', {
      params: { photo_id: props.photoId },
    })
    faces.value = res.data.faces || []
    imageSize.value = {
      width: res.data.image_width,
      height: res.data.image_height,
    }
    detected.value = true
    const enrollable = faces.value.filter((f) => f.enrollable !== false)
    if (enrollable.length === 1) {
      selectedIndex.value = enrollable[0].index
    } else if (faces.value.length === 1 && faces.value[0].enrollable !== false) {
      selectedIndex.value = faces.value[0].index
    } else {
      selectedIndex.value = null
    }
    updateDisplaySize()
  } catch (error) {
    faces.value = []
    detectError.value = error.response?.data?.detail || '人脸检测失败'
  } finally {
    detecting.value = false
  }
}

function selectFace(face) {
  selectedIndex.value = face.index
}

function onTableSelect(row) {
  if (row) selectedIndex.value = row.index
}

function onExistingPick(personId) {
  const found = registryPeople.value.find((p) => p.person_id === personId)
  if (found) {
    form.value.name = found.name
    form.value.role = found.role || 'other'
    form.value.birth_date = found.birth_date || ''
  }
}

function openEnroll(face) {
  if (!face) {
    ElMessage.warning('请先选择一张脸')
    return
  }
  if (face.enrollable === false) {
    ElMessage.warning(face.enroll_skip_reason || '该人脸质量不足，不能入库')
    return
  }
  enrollFaceIndex.value = face.index
  selectedIndex.value = face.index
  if (face.matched?.id) {
    memberMode.value = 'existing'
    form.value.person_id = face.matched.id
    form.value.name = face.matched.name || face.matched.id
    onExistingPick(face.matched.id)
  } else {
    memberMode.value = 'new'
    form.value.person_id = ''
    form.value.name = ''
    form.value.role = 'friend'
    form.value.birth_date = ''
    form.value.use_global_threshold = true
    form.value.match_threshold = 0.55
  }
  form.value.reidentify_photo = true
  dialogVisible.value = true
}

function resetForm() {
  enrollFaceIndex.value = null
}

async function submitEnroll() {
  const personId = form.value.person_id.trim()
  const name = form.value.name.trim()
  if (!personId) {
    ElMessage.warning('请填写 person_id')
    return
  }
  if (memberMode.value === 'new' && !name) {
    ElMessage.warning('新建成员请填写中文名')
    return
  }
  if (enrollFaceIndex.value === null) {
    ElMessage.warning('未选择人脸')
    return
  }

  enrolling.value = true
  try {
    const payload = {
      photo_id: props.photoId,
      person_id: personId,
      name: memberMode.value === 'existing' ? name || personId : name,
      role: form.value.role,
      birth_date: form.value.birth_date,
      face_index: enrollFaceIndex.value,
      reidentify_photo: form.value.reidentify_photo,
    }
    if (memberMode.value === 'new' && !form.value.use_global_threshold) {
      payload.match_threshold = form.value.match_threshold
    }
    const res = await axios.post('/api/face/enroll', payload)
    ElMessage.success(
      `已入库 ${res.data.name || personId}` +
        (res.data.photo_reidentified ? '，本张已重识别' : ''),
    )
    dialogVisible.value = false
    emit('enrolled')
    await detectFaces()
    await loadRegistry()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '入库失败')
  } finally {
    enrolling.value = false
  }
}

watch(
  () => props.photoId,
  () => {
    faces.value = []
    detected.value = false
    detectError.value = ''
    selectedIndex.value = null
    if (props.hasPhotoFile) {
      loadRegistry()
      detectFaces()
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.face-enroll-panel {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.panel-header h3 {
  margin: 0;
  font-size: 1rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.photo-stage {
  margin-bottom: 0.75rem;
}

.photo-wrap {
  position: relative;
  display: inline-block;
  max-width: 100%;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--panel);
}

.stage-image {
  display: block;
  max-width: 100%;
  max-height: 420px;
  object-fit: contain;
}

.face-box {
  position: absolute;
  border: 2px solid rgba(91, 159, 212, 0.85);
  background: rgba(91, 159, 212, 0.12);
  cursor: pointer;
  padding: 0;
  box-sizing: border-box;
}

.face-box.selected {
  border-color: #f0c040;
  background: rgba(240, 192, 64, 0.2);
  box-shadow: 0 0 0 1px rgba(240, 192, 64, 0.5);
}

.face-box.disabled {
  border-color: rgba(140, 140, 140, 0.7);
  background: rgba(120, 120, 120, 0.15);
  cursor: not-allowed;
}

.face-box.disabled.selected {
  border-color: rgba(160, 160, 160, 0.9);
  box-shadow: none;
}

.face-label {
  position: absolute;
  top: 2px;
  left: 2px;
  font-size: 10px;
  line-height: 1;
  padding: 2px 4px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  border-radius: 3px;
}

.face-table {
  margin-bottom: 0.75rem;
}

.actions {
  margin-bottom: 0.5rem;
}

.hint {
  font-size: 0.8rem;
  margin: 0.35rem 0 0.75rem;
}

.hint.muted,
.muted {
  color: var(--muted);
}

.hint.error {
  color: #e07070;
}

.field-hint {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.25rem;
}

.threshold-check {
  margin-left: 0.75rem;
  vertical-align: middle;
}
</style>
