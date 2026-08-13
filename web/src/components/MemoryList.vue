<template>
  <div class="list-container">
    <div class="search-bar">
      <div class="filter-row">
        <el-select
          v-model="yearFilter"
          placeholder="按年"
          clearable
          class="year-select"
          @change="handleYearChange"
        >
          <el-option
            v-for="y in years"
            :key="y"
            :label="`${y} 年`"
            :value="y"
          />
        </el-select>
        <el-select-v2
          v-model="folderFilter"
          placeholder="按文件夹"
          clearable
          filterable
          class="folder-select"
          :options="folderSelectOptions"
          @change="handleFolderChange"
        />
        <el-date-picker
          v-model="dateFrom"
          type="date"
          placeholder="起始日期"
          class="date-picker"
          value-format="YYYY-MM-DD"
          clearable
          @change="handleFilterChange"
        />
        <span class="date-separator">至</span>
        <el-date-picker
          v-model="dateTo"
          type="date"
          placeholder="结束日期"
          class="date-picker"
          value-format="YYYY-MM-DD"
          clearable
          @change="handleFilterChange"
        />
        <el-select
          v-model="sortOrder"
          placeholder="排序"
          class="sort-select"
          @change="handleFilterChange"
        >
          <el-option label="时间倒序（新→旧）" value="desc" />
          <el-option label="时间正序（旧→新）" value="asc" />
          <el-option label="按文件夹顺序" value="folder" />
        </el-select>
        <el-select
          v-model="timestampFilter"
          placeholder="时间状态"
          clearable
          class="timestamp-select"
          @change="handleTimestampFilterChange"
        >
          <el-option label="无时间" value="empty" />
          <el-option label="无时间（含前后邻居）" value="empty_context" />
        </el-select>
        <el-select
          v-model="personFilter"
          placeholder="按人物筛选"
          clearable
          class="person-select"
          filterable
          @change="handleFilterChange"
        >
          <el-option value="__EMPTY__" label="(无人物)" />
          <el-option
            v-for="person in registryPeople"
            :key="person.person_id"
            :label="person.name"
            :value="person.name"
          />
        </el-select>
        <el-select-v2
          v-model="locationFilter"
          placeholder="按地址筛选"
          clearable
          filterable
          class="location-select"
          :options="locationSelectOptions"
          @change="handleFilterChange"
        />
        <el-select
          v-model="faceFilter"
          placeholder="人脸状态"
          clearable
          class="face-select"
          @change="handleFilterChange"
        >
          <el-option label="检测到人脸" value="yes" />
          <el-option label="无人脸" value="no" />
          <el-option label="有脸未识别" value="needs_faces" />
        </el-select>
        <el-select
          v-model="mediaTypeFilter"
          placeholder="媒体类型"
          clearable
          class="media-select"
          @change="handleFilterChange"
        >
          <el-option label="照片" value="photo" />
          <el-option label="视频" value="video" />
          <el-option label="音频" value="audio" />
        </el-select>
      </div>
      <div class="filter-row">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索 id、时间、地点、人物、场景"
          clearable
          class="search-input"
          @keyup.enter="loadData"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="loadData">搜索</el-button>
        <el-button @click="resetSearch">重置</el-button>
      </div>
    </div>

    <div class="batch-bar">
      <span class="batch-count">已选 {{ selectedRows.length }} 条（本页）</span>
      <el-button size="small" @click="selectAllPage">全选本页</el-button>
      <el-button size="small" :disabled="!selectedRows.length" @click="clearSelection">取消选择</el-button>
      <el-button
        type="primary"
        size="small"
        :disabled="!selectedRows.length"
        @click="openPeopleDialog"
      >
        批量标人物
      </el-button>
      <el-button
        type="primary"
        size="small"
        plain
        :disabled="!selectedRows.length"
        @click="openLocationDialog"
      >
        批量标地址
      </el-button>
      <el-button
        type="warning"
        size="small"
        plain
        :disabled="!selectedRows.length"
        @click="openTimestampDialog"
      >
        批量补时间
      </el-button>
      <el-button
        type="danger"
        size="small"
        :disabled="!selectedRows.length"
        :loading="deleting"
        @click="deleteSelected"
      >
        删除选中
      </el-button>
      <span class="batch-hint">拖拽框选 · ⌘/Ctrl 点选 · Shift 连选 · 单击进详情</span>
    </div>

    <el-dialog v-model="peopleDialogVisible" title="批量标人物" width="480px" destroy-on-close>
      <p class="dialog-hint">将写入选中照片的 JSON people，并同步 SQLite（不加入脸库）。</p>
      <el-form label-width="88px">
        <el-form-item label="人物">
          <el-select
            v-model="batchPersonIds"
            multiple
            filterable
            placeholder="从人脸库选择"
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
        <el-form-item label="模式">
          <el-radio-group v-model="peopleMode">
            <el-radio value="append">追加（保留已有）</el-radio>
            <el-radio value="replace">替换（覆盖已有）</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="peopleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSaving" @click="submitBatchPeople">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="locationDialogVisible" title="批量标地址" width="520px" destroy-on-close>
      <p class="dialog-hint">将写入选中照片的 location，并标记 manual_location。</p>
      <el-form label-width="88px">
        <el-form-item label="地址">
          <el-select
            v-model="batchLocation"
            filterable
            allow-create
            default-first-option
            placeholder="选择已有或输入新地址"
            style="width: 100%"
            @change="onBatchLocationChange"
          >
            <el-option
              v-for="item in locationItems"
              :key="item.location"
              :label="item.location"
              :value="item.location"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="省">
          <el-input v-model="batchProvince" placeholder="可选" />
        </el-form-item>
        <el-form-item label="市">
          <el-input v-model="batchCity" placeholder="可选" />
        </el-form-item>
        <el-form-item label="区">
          <el-input v-model="batchDistrict" placeholder="可选" />
        </el-form-item>
        <el-form-item label="详细地址">
          <el-input v-model="batchFormattedAddress" placeholder="可选，高德原文" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="locationDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSaving" @click="submitBatchLocation">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="timestampDialogVisible" title="批量补时间" width="420px" destroy-on-close>
      <p class="dialog-hint">写入 YYYY-MM-DD 即可；会标记 manual_edit，并刷新人物年龄。</p>
      <el-form label-width="88px">
        <el-form-item label="日期">
          <el-date-picker
            v-model="batchTimestamp"
            type="date"
            placeholder="选择日期"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="timestampDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSaving" @click="submitBatchTimestamp">确定</el-button>
      </template>
    </el-dialog>

    <div
      ref="scrollRef"
      class="photo-scroll"
      :class="{ 'is-selecting': !!marquee }"
      @pointerdown="onScrollPointerDown"
    >
      <div class="photo-scroll-inner">
        <div ref="gridRef" class="photo-grid">
          <article
            v-for="(row, index) in tableData"
            :key="row.photo_id"
            class="photo-card"
            :class="{
              selected: isSelected(row.photo_id),
              'no-time': !row.timestamp,
              context: !!row.is_context,
            }"
            :data-photo-id="row.photo_id"
            @click="onCardClick(row, index, $event)"
          >
            <div class="card-image">
              <img
                v-if="row.has_file"
                :src="getPreviewUrl(row.source_path)"
                :alt="row.photo_id"
                loading="lazy"
                decoding="async"
                draggable="false"
              />
              <div v-else class="card-no-image">无图</div>
              <span v-if="row.media_type === 'video'" class="media-badge">视频</span>
              <span v-else-if="row.media_type === 'audio'" class="media-badge audio">音频</span>
              <button
                type="button"
                class="card-check"
                :class="{ checked: isSelected(row.photo_id) }"
                :aria-label="isSelected(row.photo_id) ? '取消选择' : '选择'"
                @click.stop="onCheckClick(row, index)"
              >
                <span class="card-check-mark" v-if="isSelected(row.photo_id)">✓</span>
              </button>
            </div>
            <div class="card-info">
              <div class="card-info-top">
                <span class="card-time" :class="{ missing: !row.timestamp }">
                  {{ row.is_context ? '邻居 · ' : '' }}{{ formatTime(row.timestamp) }}
                </span>
                <el-tag
                  :type="row.face_detected ? 'success' : 'info'"
                  size="small"
                  effect="dark"
                >
                  {{ row.face_detected ? '有脸' : '无人脸' }}
                </el-tag>
              </div>
              <div
                v-if="row.folder"
                class="card-meta folder"
                :title="row.folder"
              >
                {{ row.folder }}
              </div>
              <div class="card-meta" :class="{ empty: !row.location }" :title="row.location || ''">
                {{ row.location || '无地址' }}
              </div>
              <div
                class="card-meta weather"
                :class="{ empty: !formatWeather(row) }"
                :title="formatWeather(row) || '无天气'"
              >
                {{ formatWeather(row) || '无天气' }}
              </div>
              <div class="card-meta" :class="{ empty: !row.people }" :title="row.people || ''">
                {{ row.people || '无人物' }}
              </div>
            </div>
          </article>
          <div v-if="!tableData.length" class="grid-empty">
            <el-empty description="没有匹配的照片" />
          </div>
        </div>
        <div
          v-if="marquee"
          class="marquee-box"
          :style="{
            left: `${marquee.left}px`,
            top: `${marquee.top}px`,
            width: `${marquee.width}px`,
            height: `${marquee.height}px`,
          }"
        />
      </div>
    </div>

    <div class="pagination-wrapper">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[30, 45, 60]"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const emit = defineEmits(['view-detail'])

const searchKeyword = ref('')
const locationFilter = ref('')
const personFilter = ref('')
const faceFilter = ref('')
const mediaTypeFilter = ref('')
const yearFilter = ref('')
const folderFilter = ref('')
const sortOrder = ref('desc')
const timestampFilter = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const years = ref([])
const folders = ref([])
const locations = ref([])
const locationItems = ref([])
const registryPeople = ref([])
const tableData = ref([])
const selectedRows = ref([])
const deleting = ref(false)
const batchSaving = ref(false)
const peopleDialogVisible = ref(false)
const locationDialogVisible = ref(false)
const timestampDialogVisible = ref(false)
const batchPersonIds = ref([])
const peopleMode = ref('append')
const batchLocation = ref('')
const batchProvince = ref('')
const batchCity = ref('')
const batchDistrict = ref('')
const batchFormattedAddress = ref('')
const batchTimestamp = ref('')
const page = ref(1)
/** 约 3 屏可滚动浏览，不强制塞进一屏 */
const pageSize = ref(45)
const total = ref(0)
const scrollRef = ref(null)
const gridRef = ref(null)
const marquee = ref(null)
const lastAnchorIndex = ref(0)
let dragState = null
let suppressClick = false

const locationSelectOptions = computed(() => [
  { value: '__EMPTY__', label: '(空地址)' },
  ...locationItems.value.map((item) => ({
    value: item.location,
    label: item.location,
  })),
])

const folderSelectOptions = computed(() =>
  folders.value.map((f) => ({
    value: f,
    label: f,
  })),
)

async function loadYears() {
  try {
    const res = await axios.get('/api/memory/years')
    years.value = res.data.years || []
  } catch (error) {
    console.error('加载年份列表失败:', error)
    years.value = []
  }
}

async function loadFolders() {
  try {
    const res = await axios.get('/api/memory/folders')
    folders.value = res.data.folders || []
  } catch (error) {
    console.error('加载文件夹列表失败:', error)
    folders.value = []
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

async function loadRegistryPeople() {
  try {
    const res = await axios.get('/api/face/registry')
    registryPeople.value = res.data.people
  } catch (error) {
    console.error('加载人物列表失败:', error)
    registryPeople.value = []
  }
}

async function loadData() {
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      sort: sortOrder.value || 'desc',
    }
    if (searchKeyword.value.trim()) {
      params.search = searchKeyword.value.trim()
    }
    if (locationFilter.value) {
      params.location = locationFilter.value
    }
    if (personFilter.value) {
      params.person = personFilter.value
    }
    if (faceFilter.value) {
      params.face = faceFilter.value
    }
    if (mediaTypeFilter.value) {
      params.media_type = mediaTypeFilter.value
    }
    if (yearFilter.value) {
      params.year = yearFilter.value
    }
    if (folderFilter.value) {
      params.folder = folderFilter.value
    }
    if (dateFrom.value) {
      params.date_from = dateFrom.value
    }
    if (dateTo.value) {
      params.date_to = dateTo.value
    }
    if (timestampFilter.value === 'empty' || timestampFilter.value === 'empty_context') {
      params.timestamp = 'empty'
    }
    if (timestampFilter.value === 'empty_context') {
      params.context_neighbors = true
      params.sort = 'folder'
    }
    const res = await axios.get('/api/memory/list', { params })
    tableData.value = res.data.items
    total.value = res.data.total
    clearSelection()
  } catch (error) {
    console.error('加载数据失败:', error)
    tableData.value = []
    total.value = 0
  }
}

function handleTimestampFilterChange() {
  if (timestampFilter.value === 'empty_context') {
    sortOrder.value = 'folder'
  }
  handleFilterChange()
}

function handleYearChange() {
  // 选年时清空日范围，避免和年份冲突；仍可用日期在年内细筛（再选手动填）
  if (yearFilter.value) {
    dateFrom.value = ''
    dateTo.value = ''
  }
  handleFilterChange()
}

function handleFolderChange() {
  // 选文件夹时按路径浏览更直观；清空年份以免 timestamp 年与目录年不一致漏结果
  if (folderFilter.value) {
    yearFilter.value = ''
    if (sortOrder.value === 'desc') {
      sortOrder.value = 'folder'
    }
  }
  handleFilterChange()
}

function handleFilterChange() {
  page.value = 1
  loadData()
}

function handleSizeChange(val) {
  pageSize.value = val
  page.value = 1
  loadData()
}

function handlePageChange(val) {
  page.value = val
  loadData()
}

function resetSearch() {
  searchKeyword.value = ''
  locationFilter.value = ''
  personFilter.value = ''
  faceFilter.value = ''
  mediaTypeFilter.value = ''
  yearFilter.value = ''
  folderFilter.value = ''
  sortOrder.value = 'desc'
  timestampFilter.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  page.value = 1
  loadData()
}

function isSelected(photoId) {
  return selectedRows.value.some((row) => row.photo_id === photoId)
}

function setSelection(rows) {
  selectedRows.value = rows
}

function toggleSelect(row, checked) {
  if (checked) {
    if (!isSelected(row.photo_id)) {
      selectedRows.value = [...selectedRows.value, row]
    }
  } else {
    selectedRows.value = selectedRows.value.filter((r) => r.photo_id !== row.photo_id)
  }
}

function selectRange(toIndex) {
  const from = Math.max(0, Math.min(lastAnchorIndex.value, tableData.value.length - 1))
  const start = Math.min(from, toIndex)
  const end = Math.max(from, toIndex)
  setSelection(tableData.value.slice(start, end + 1))
}

function onCheckClick(row, index) {
  toggleSelect(row, !isSelected(row.photo_id))
  lastAnchorIndex.value = index
}

function onCardClick(row, index, event) {
  if (suppressClick) {
    suppressClick = false
    return
  }
  if (event.shiftKey) {
    selectRange(index)
    return
  }
  if (event.metaKey || event.ctrlKey) {
    toggleSelect(row, !isSelected(row.photo_id))
    lastAnchorIndex.value = index
    return
  }
  viewDetail(row.photo_id)
}

function selectAllPage() {
  selectedRows.value = [...tableData.value]
  lastAnchorIndex.value = 0
}

function clearSelection() {
  selectedRows.value = []
}

function contentPointFromEvent(event) {
  const el = scrollRef.value
  if (!el) return { x: 0, y: 0 }
  const rect = el.getBoundingClientRect()
  return {
    x: event.clientX - rect.left + el.scrollLeft,
    y: event.clientY - rect.top + el.scrollTop,
  }
}

function cardContentRect(cardEl) {
  const scrollEl = scrollRef.value
  if (!scrollEl || !cardEl) return null
  const scrollRect = scrollEl.getBoundingClientRect()
  const cardRect = cardEl.getBoundingClientRect()
  return {
    left: cardRect.left - scrollRect.left + scrollEl.scrollLeft,
    top: cardRect.top - scrollRect.top + scrollEl.scrollTop,
    right: cardRect.right - scrollRect.left + scrollEl.scrollLeft,
    bottom: cardRect.bottom - scrollRect.top + scrollEl.scrollTop,
  }
}

function rectsIntersect(a, b) {
  return !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom)
}

function applyMarqueeSelection() {
  if (!marquee.value || !gridRef.value) return
  const box = {
    left: marquee.value.left,
    top: marquee.value.top,
    right: marquee.value.left + marquee.value.width,
    bottom: marquee.value.top + marquee.value.height,
  }
  const hit = []
  const cards = gridRef.value.querySelectorAll('.photo-card')
  cards.forEach((el) => {
    const photoId = el.getAttribute('data-photo-id')
    const rect = cardContentRect(el)
    if (!rect || !photoId) return
    if (!rectsIntersect(box, rect)) return
    const row = tableData.value.find((item) => item.photo_id === photoId)
    if (row) hit.push(row)
  })
  if (dragState?.additive) {
    const map = new Map()
    for (const row of dragState.baseSelection) map.set(row.photo_id, row)
    for (const row of hit) map.set(row.photo_id, row)
    setSelection([...map.values()])
  } else {
    setSelection(hit)
  }
}

function onScrollPointerDown(event) {
  if (event.button !== 0) return
  if (event.target.closest('.card-check')) return
  if (event.target.closest('.el-empty')) return

  const point = contentPointFromEvent(event)
  dragState = {
    startX: point.x,
    startY: point.y,
    originClientX: event.clientX,
    originClientY: event.clientY,
    additive: event.metaKey || event.ctrlKey,
    moved: false,
    baseSelection: event.metaKey || event.ctrlKey ? [...selectedRows.value] : [],
  }
  marquee.value = null

  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onWindowPointerUp)
}

function onWindowPointerMove(event) {
  if (!dragState) return
  const dx = event.clientX - dragState.originClientX
  const dy = event.clientY - dragState.originClientY
  if (!dragState.moved && Math.hypot(dx, dy) < 6) return
  dragState.moved = true
  suppressClick = true

  const point = contentPointFromEvent(event)
  const left = Math.min(dragState.startX, point.x)
  const top = Math.min(dragState.startY, point.y)
  marquee.value = {
    left,
    top,
    width: Math.abs(point.x - dragState.startX),
    height: Math.abs(point.y - dragState.startY),
  }
  applyMarqueeSelection()
}

function onWindowPointerUp() {
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onWindowPointerUp)
  if (dragState?.moved) {
    suppressClick = true
    setTimeout(() => {
      suppressClick = false
    }, 0)
  }
  dragState = null
  marquee.value = null
}

async function deleteSelected() {
  const ids = selectedRows.value.map((row) => row.photo_id).filter(Boolean)
  if (ids.length === 0) {
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${ids.length} 条记录？\n\n原图 + memory JSON 会移入 data/.trash/\nSQLite 索引同步清除（无需再 sync）`,
      '批量删除',
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

  deleting.value = true
  try {
    const res = await axios.post('/api/delete/batch', { photo_ids: ids })
    const { deleted_count: deletedCount, failed_count: failedCount, failed } = res.data
    if (failedCount > 0) {
      const detail = failed.map((item) => `${item.photo_id}: ${item.error}`).join('\n')
      ElMessage.warning(`已删除 ${deletedCount} 条，失败 ${failedCount} 条\n${detail}`)
    } else {
      ElMessage.success(`已删除 ${deletedCount} 条`)
    }
    await loadData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批量删除失败')
  } finally {
    deleting.value = false
  }
}

function openPeopleDialog() {
  batchPersonIds.value = []
  peopleMode.value = 'append'
  peopleDialogVisible.value = true
}

async function openLocationDialog() {
  batchLocation.value = ''
  batchProvince.value = ''
  batchCity.value = ''
  batchDistrict.value = ''
  batchFormattedAddress.value = ''
  await loadLocations()
  locationDialogVisible.value = true
}

function openTimestampDialog() {
  batchTimestamp.value = ''
  timestampDialogVisible.value = true
}

function onBatchLocationChange(loc) {
  const item = locationItems.value.find((entry) => entry.location === loc)
  if (!item) {
    return
  }
  batchProvince.value = item.province || ''
  batchCity.value = item.city || ''
  batchDistrict.value = item.district || ''
  batchFormattedAddress.value = item.formatted_address || item.location || ''
}

function reportBatchResult(res) {
  const { updated, failed_count: failedCount, failed } = res.data
  if (failedCount > 0) {
    const detail = failed.map((item) => `${item.photo_id}: ${item.error}`).join('\n')
    ElMessage.warning(`已更新 ${updated} 条，失败 ${failedCount} 条\n${detail}`)
  } else {
    ElMessage.success(`已更新 ${updated} 条`)
  }
}

async function submitBatchPeople() {
  const ids = selectedRows.value.map((row) => row.photo_id).filter(Boolean)
  if (!batchPersonIds.value.length) {
    ElMessage.warning('请选择人物')
    return
  }
  batchSaving.value = true
  try {
    const res = await axios.post('/api/memory/batch-update-people', {
      photo_ids: ids,
      person_ids: batchPersonIds.value,
      mode: peopleMode.value,
    })
    reportBatchResult(res)
    peopleDialogVisible.value = false
    await loadData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批量标人物失败')
  } finally {
    batchSaving.value = false
  }
}

async function submitBatchLocation() {
  const ids = selectedRows.value.map((row) => row.photo_id).filter(Boolean)
  if (!batchLocation.value.trim()) {
    ElMessage.warning('请填写地址')
    return
  }
  batchSaving.value = true
  try {
    const res = await axios.post('/api/memory/batch-update-location-by-ids', {
      photo_ids: ids,
      location: batchLocation.value.trim(),
      province: batchProvince.value.trim(),
      city: batchCity.value.trim(),
      district: batchDistrict.value.trim(),
      formatted_address: batchFormattedAddress.value.trim(),
    })
    reportBatchResult(res)
    locationDialogVisible.value = false
    await Promise.all([loadData(), loadLocations()])
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批量标地址失败')
  } finally {
    batchSaving.value = false
  }
}

async function submitBatchTimestamp() {
  const ids = selectedRows.value
    .filter((row) => !row.is_context)
    .map((row) => row.photo_id)
    .filter(Boolean)
  if (!batchTimestamp.value) {
    ElMessage.warning('请选择日期')
    return
  }
  if (!ids.length) {
    ElMessage.warning('请选择需要补时间的照片（邻居对照项不会写入）')
    return
  }
  batchSaving.value = true
  try {
    const res = await axios.post('/api/memory/batch-update-timestamp', {
      photo_ids: ids,
      timestamp: batchTimestamp.value,
      only_if_empty: false,
    })
    reportBatchResult(res)
    timestampDialogVisible.value = false
    await loadData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批量补时间失败')
  } finally {
    batchSaving.value = false
  }
}

function viewDetail(photoId) {
  emit('view-detail', photoId)
}

function getPreviewUrl(path) {
  return `/api/preview?path=${encodeURIComponent(path)}&size=640`
}

function formatWeather(row) {
  const condition = (row?.weather_condition || '').trim()
  if (!condition) return ''
  const min = row.weather_temp_min_c
  const max = row.weather_temp_max_c
  const mean = row.weather_temp_mean_c
  if (min != null && max != null && !Number.isNaN(Number(min)) && !Number.isNaN(Number(max))) {
    return `${condition} · ${Math.round(Number(min))}–${Math.round(Number(max))}℃`
  }
  if (mean != null && !Number.isNaN(Number(mean))) {
    return `${condition} · ${Math.round(Number(mean))}℃`
  }
  return condition
}

function formatTime(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return timestamp
  const y = date.getFullYear()
  const m = date.getMonth() + 1
  const d = date.getDate()
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${y}/${m}/${d} ${hh}:${mm}`
}

onMounted(() => {
  loadYears()
  loadFolders()
  loadLocations()
  loadRegistryPeople()
  loadData()
})

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onWindowPointerUp)
})
</script>

<style scoped>
.list-container {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.search-bar {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
}

.year-select {
  width: 110px;
}

.folder-select {
  width: 200px;
}

.date-picker {
  width: 150px;
}

.date-separator {
  color: var(--muted);
  font-size: 0.9rem;
}

.sort-select {
  width: 180px;
}

.timestamp-select {
  width: 200px;
}

.person-select {
  width: 140px;
}

.location-select {
  width: 180px;
}

.location-select :deep(.el-select-v2__wrapper) {
  width: 180px;
}

.face-select {
  width: 150px;
}

.media-select {
  width: 120px;
}

.search-input {
  flex: 1;
  min-width: 200px;
  max-width: 500px;
}

.batch-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
  padding: 0.65rem 0.85rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
}

.batch-count {
  color: var(--text);
  font-size: 0.9rem;
  font-weight: 500;
}

.batch-hint {
  margin-left: auto;
  color: var(--muted);
  font-size: 0.78rem;
}

.dialog-hint {
  margin: 0 0 1rem;
  color: var(--muted);
  font-size: 0.9rem;
  line-height: 1.5;
}

.photo-scroll {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
}

.photo-scroll.is-selecting {
  user-select: none;
  cursor: crosshair;
}

.photo-scroll.is-selecting .photo-card {
  pointer-events: none;
}

.photo-scroll-inner {
  position: relative;
  min-height: 100%;
}

.marquee-box {
  position: absolute;
  z-index: 20;
  box-sizing: border-box;
  border: 1px solid color-mix(in srgb, var(--accent) 80%, #fff);
  background: color-mix(in srgb, var(--accent) 22%, transparent);
  pointer-events: none;
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(8, minmax(100px, 1fr));
  grid-auto-rows: max-content;
  gap: 0.45rem;
  align-content: start;
  align-items: start;
  height: auto;
  padding-bottom: 0.5rem;
}

@media (max-width: 1400px) {
  .photo-grid {
    grid-template-columns: repeat(6, minmax(90px, 1fr));
  }
}

@media (max-width: 1100px) {
  .photo-grid {
    grid-template-columns: repeat(4, minmax(90px, 1fr));
  }
}

@media (max-width: 720px) {
  .photo-grid {
    grid-template-columns: repeat(3, minmax(80px, 1fr));
  }
}

@media (max-width: 480px) {
  .photo-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.photo-card {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: max-content;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0d1117;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.photo-card:hover {
  border-color: var(--accent);
}

.photo-card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 40%, transparent);
}

.photo-card.no-time {
  border-color: #c47a1a;
}

.photo-card.context {
  opacity: 0.72;
}

.card-image {
  position: relative;
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  flex: none;
  background: #010409;
  overflow: hidden;
}

.card-image img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center;
  display: block;
}

.media-badge {
  position: absolute;
  left: 0.35rem;
  bottom: 0.35rem;
  z-index: 2;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  font-size: 0.7rem;
  line-height: 1.2;
  color: #fff;
  background: rgba(0, 0, 0, 0.65);
  pointer-events: none;
}

.media-badge.audio {
  background: rgba(30, 80, 120, 0.8);
}

.card-no-image {
  width: 100%;
  height: 100%;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 0.75rem;
}

.card-check {
  position: absolute;
  top: 0.25rem;
  left: 0.25rem;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #222;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
  cursor: pointer;
  pointer-events: auto;
}

.card-check.checked {
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
}

.card-check-mark {
  color: #fff;
  font-size: 0.95rem;
  font-weight: 700;
  line-height: 1;
}

.card-info {
  flex: 0 0 auto;
  display: block;
  padding: 0.3rem 0.35rem 0.35rem;
  background: #21262d;
  border-top: 1px solid #30363d;
}

.card-info-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.25rem;
  margin-bottom: 0.12rem;
}

.card-time {
  color: #fff;
  font-size: 0.62rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-time.missing {
  color: #f0a020;
}

.card-info-top :deep(.el-tag) {
  flex-shrink: 0;
  transform: scale(0.78);
  transform-origin: right center;
}

.card-meta {
  color: #e6edf3;
  font-size: 0.62rem;
  font-weight: 500;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-meta.folder {
  color: #8b9cb3;
}

.card-meta.weather:not(.empty) {
  color: #9ecbff;
}

.card-meta.empty {
  color: #8b949e;
  font-weight: 400;
}

.grid-empty {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem 0;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 1rem;
}
</style>
