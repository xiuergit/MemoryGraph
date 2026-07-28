<template>
  <div class="cache-container">
    <div class="cache-header">
      <div class="stats-row" v-if="stats">
        <el-tag type="info">坐标映射 {{ stats.coords }}</el-tag>
        <el-tag type="success">地址名 {{ stats.locations }}</el-tag>
        <el-tag v-if="stats.missing_admin" type="warning">缺省市区 {{ stats.missing_admin }}</el-tag>
        <el-tag v-if="stats.invalid" type="danger">不合格 {{ stats.invalid }}</el-tag>
        <span class="hint">真源：data/.geocode_cache.json · 编辑时可看样本图 · 改完再跑 regeocode</span>
      </div>

      <div class="toolbar">
        <el-radio-group v-model="mode" @change="onModeChange">
          <el-radio-button value="grouped">按地址合并</el-radio-button>
          <el-radio-button value="coords">按坐标</el-radio-button>
        </el-radio-group>
        <el-select
          v-model="provinceFilter"
          placeholder="按省筛选"
          clearable
          filterable
          class="region-select"
          @change="onProvinceChange"
        >
          <el-option
            v-for="p in provinces"
            :key="p.province"
            :label="`${p.province}（${p.location_count}）`"
            :value="p.province"
          />
        </el-select>
        <el-select
          v-model="cityFilter"
          placeholder="按市筛选"
          clearable
          filterable
          class="region-select"
          :disabled="!provinceFilter"
          @change="loadData"
        >
          <el-option
            v-for="c in cityOptions"
            :key="c.city"
            :label="`${c.city}（${c.location_count}）`"
            :value="c.city"
          />
        </el-select>
        <el-select v-model="sortBy" class="sort-select" @change="loadData">
          <el-option label="坐标数优先" value="coord_count" />
          <el-option label="省市优先" value="region" />
        </el-select>
        <el-input
          v-model="search"
          placeholder="搜索地址名 / 详细地址 / 坐标"
          clearable
          class="search-input"
          @keyup.enter="loadData"
        />
        <el-button type="primary" @click="loadData">搜索</el-button>
        <el-button @click="resetSearch">重置</el-button>
      </div>
    </div>

    <el-table
      v-loading="loading"
      :data="items"
      stripe
      class="cache-table"
      :span-method="mode === 'grouped' && sortBy === 'region' ? spanMethod : undefined"
    >
      <el-table-column label="省" width="100">
        <template #default="scope">
          <span class="cell-region">{{ displayRegion(scope.row.province) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="市" width="100">
        <template #default="scope">
          <span class="cell-region">{{ displayRegion(scope.row.city) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="区" width="90">
        <template #default="scope">
          <span class="cell-text">{{ scope.row.district || '-' }}</span>
        </template>
      </el-table-column>

      <el-table-column v-if="mode === 'grouped'" label="短地名" min-width="130">
        <template #default="scope">
          <span class="location-name">{{ scope.row.location || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="mode === 'grouped'" label="坐标数" width="80" align="center">
        <template #default="scope">
          <span class="cell-strong">{{ scope.row.coord_count }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="mode === 'coords'" label="短地名" min-width="120">
        <template #default="scope">
          <span class="location-name">{{ scope.row.location || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="mode === 'coords'" label="坐标" min-width="170">
        <template #default="scope">
          <span class="cell-mono">{{ scope.row.coords }}</span>
        </template>
      </el-table-column>

      <el-table-column label="详细地址" min-width="220">
        <template #default="scope">
          <span :class="scope.row.missing_admin ? 'cell-warn' : 'cell-text'">
            {{ scope.row.formatted_address || '-' }}
          </span>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="110" align="center">
        <template #default="scope">
          <el-tag v-if="!scope.row.valid" type="danger" size="small">不合格</el-tag>
          <el-tag v-else-if="scope.row.admin_inconsistent" type="danger" size="small">省市不一</el-tag>
          <el-tag v-else-if="scope.row.missing_admin" type="warning" size="small">缺 admin</el-tag>
          <el-tag v-else type="success" size="small">OK</el-tag>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="100" align="center" fixed="right">
        <template #default="scope">
          <el-button type="primary" link size="small" @click="openEdit(scope.row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100, 200]"
        layout="total, sizes, prev, pager, next"
        @current-change="loadData"
        @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="editVisible" :title="editTitle" width="720px" class="cache-edit-dialog">
      <el-form label-width="88px" class="cache-edit-form">
        <el-form-item v-if="editMode === 'coords'" label="坐标">
          <el-input v-model="form.coords" disabled />
        </el-form-item>
        <el-form-item v-if="editMode === 'grouped'" label="原地址">
          <el-input v-model="form.old_location" disabled />
        </el-form-item>

        <div v-loading="samplesLoading" class="sample-section">
          <div class="sample-header">
            <span class="sample-title">样本照片</span>
            <span class="sample-meta">
              <template v-if="samplePhotoCount > 0">
                库中约 {{ samplePhotoCount }} 张
                <template v-if="editMode === 'grouped' && sampleCoordCount > 0">
                  · 抽 {{ sampleCoordCount }} 个坐标
                </template>
              </template>
              <template v-else-if="!samplesLoading">暂无匹配照片（可能尚未 sync 索引）</template>
            </span>
          </div>
          <p class="sample-hint">对照照片核对短地名与详细地址；点击缩略图可查看详情</p>
          <div v-if="sampleItems.length" class="sample-grid">
            <div
              v-for="item in sampleItems"
              :key="item.photo_id"
              class="sample-card"
              @click="viewSampleDetail(item.photo_id)"
            >
              <div class="sample-thumb-wrap">
                <img
                  v-if="item.has_file"
                  :src="getPreviewUrl(item.source_path)"
                  :alt="item.photo_id"
                  class="sample-thumb"
                  loading="lazy"
                />
                <span v-else class="sample-no-image">无图</span>
              </div>
              <div class="sample-caption">
                <div class="sample-time">{{ formatSampleTime(item.timestamp) }}</div>
                <div class="sample-loc">{{ item.location || '—' }}</div>
                <div v-if="editMode === 'grouped'" class="sample-coords">{{ item.cache_coords }}</div>
              </div>
            </div>
          </div>
        </div>

        <el-form-item label="短地名">
          <el-input v-model="form.location" placeholder="如：李子园公园" />
        </el-form-item>
        <el-form-item label="省">
          <el-input v-model="form.province" />
        </el-form-item>
        <el-form-item label="市">
          <el-input v-model="form.city" />
        </el-form-item>
        <el-form-item label="区">
          <el-input v-model="form.district" />
        </el-form-item>
        <el-form-item label="详细地址">
          <el-input
            v-model="form.formatted_address"
            type="textarea"
            :rows="2"
            placeholder="高德完整地址，应与短地名不同"
          />
        </el-form-item>
        <p v-if="editMode === 'grouped'" class="edit-hint">
          将更新缓存中所有「{{ form.old_location }}」的坐标映射（共 {{ form.coord_count }} 个）
        </p>
      </el-form>
      <template #footer>
        <el-button
          v-if="editMode === 'coords'"
          type="danger"
          plain
          @click="confirmDelete"
        >
          删除此坐标
        </el-button>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存到缓存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const emit = defineEmits(['view-detail'])

const mode = ref('grouped')
const search = ref('')
const sortBy = ref('coord_count')
const provinceFilter = ref('')
const cityFilter = ref('')
const provinces = ref([])
const page = ref(1)
const pageSize = ref(100)
const total = ref(0)
const items = ref([])
const loading = ref(false)
const stats = ref(null)
const spanMap = ref({ province: [], city: [] })

const cityOptions = computed(() => {
  if (!provinceFilter.value) return []
  const hit = provinces.value.find(p => p.province === provinceFilter.value)
  return hit?.cities || []
})

function displayRegion(value) {
  const text = (value || '').trim()
  return text || '未分区'
}

function regionKey(value) {
  return (value || '').trim() || '未分区'
}

function computeSpans(list) {
  const provinceSpans = []
  const citySpans = []
  let i = 0
  while (i < list.length) {
    const p = regionKey(list[i].province)
    let j = i
    while (j < list.length && regionKey(list[j].province) === p) j += 1
    provinceSpans[i] = j - i
    for (let k = i + 1; k < j; k++) provinceSpans[k] = 0

    let k = i
    while (k < j) {
      const c = regionKey(list[k].city)
      let m = k
      while (m < j && regionKey(list[m].city) === c) m += 1
      citySpans[k] = m - k
      for (let n = k + 1; n < m; n++) citySpans[n] = 0
      k = m
    }
    i = j
  }
  spanMap.value = { province: provinceSpans, city: citySpans }
}

function spanMethod({ rowIndex, columnIndex }) {
  if (mode.value !== 'grouped') return undefined
  if (columnIndex === 0) {
    const rowspan = spanMap.value.province[rowIndex] ?? 1
    return rowspan === 0 ? [0, 0] : [rowspan, 1]
  }
  if (columnIndex === 1) {
    const rowspan = spanMap.value.city[rowIndex] ?? 1
    return rowspan === 0 ? [0, 0] : [rowspan, 1]
  }
  return undefined
}

async function loadRegions() {
  try {
    const res = await axios.get('/api/geocode/cache/regions')
    provinces.value = res.data.provinces || []
  } catch (error) {
    console.error('加载省市区列表失败:', error)
  }
}

const editVisible = ref(false)
const editMode = ref('grouped')
const saving = ref(false)
const form = ref({
  coords: '',
  old_location: '',
  location: '',
  province: '',
  city: '',
  district: '',
  formatted_address: '',
  coord_count: 0,
})

const editTitle = computed(() =>
  editMode.value === 'grouped' ? '编辑地址（批量更新缓存）' : '编辑坐标映射'
)

const sampleItems = ref([])
const samplesLoading = ref(false)
const samplePhotoCount = ref(0)
const sampleCoordCount = ref(0)

function getPreviewUrl(path) {
  return `/api/preview?path=${encodeURIComponent(path)}`
}

function formatSampleTime(timestamp) {
  if (!timestamp) return '—'
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return timestamp.slice(0, 10)
  return date.toLocaleDateString('zh-CN')
}

function viewSampleDetail(photoId) {
  if (!photoId) return
  emit('view-detail', photoId)
}

async function loadSamples() {
  samplesLoading.value = true
  sampleItems.value = []
  samplePhotoCount.value = 0
  sampleCoordCount.value = 0
  try {
    const params = { limit: 6 }
    if (editMode.value === 'coords' && form.value.coords) {
      params.coords = form.value.coords
    } else if (form.value.old_location) {
      params.location = form.value.old_location
    } else {
      return
    }
    const res = await axios.get('/api/geocode/cache/samples', { params })
    sampleItems.value = res.data.items || []
    samplePhotoCount.value = res.data.photo_count || 0
    sampleCoordCount.value = (res.data.sample_coords || []).length
  } catch (error) {
    console.error('加载样本照片失败:', error)
    ElMessage.warning('样本照片加载失败')
  } finally {
    samplesLoading.value = false
  }
}

async function loadStats() {
  try {
    const res = await axios.get('/api/geocode/cache/stats')
    stats.value = res.data
  } catch (error) {
    console.error('加载缓存统计失败:', error)
  }
}

async function loadData() {
  loading.value = true
  try {
    const res = await axios.get('/api/geocode/cache', {
      params: {
        mode: mode.value,
        search: search.value.trim(),
        province: provinceFilter.value,
        city: cityFilter.value,
        sort: sortBy.value,
        page: page.value,
        page_size: pageSize.value,
      },
    })
    items.value = res.data.items
    total.value = res.data.total
    if (mode.value === 'grouped') {
      computeSpans(items.value)
    }
  } catch (error) {
    const detail = error.response?.data?.detail
    const status = error.response?.status
    const msg = detail || (status ? `HTTP ${status}` : error.message)
    console.error('加载缓存失败:', error)
    ElMessage.error(`加载缓存失败：${msg}（请确认 memory_desk 已启动，并重启 npm run dev 同步端口）`)
  } finally {
    loading.value = false
  }
}

function resetSearch() {
  search.value = ''
  provinceFilter.value = ''
  cityFilter.value = ''
  page.value = 1
  loadData()
}

function onModeChange() {
  page.value = 1
  loadData()
}

function onProvinceChange() {
  cityFilter.value = ''
  page.value = 1
  loadData()
}

function handleSizeChange() {
  page.value = 1
  loadData()
}

async function openEdit(row) {
  editMode.value = mode.value
  if (mode.value === 'grouped') {
    form.value = {
      coords: '',
      old_location: row.location,
      location: row.location,
      province: row.province || '',
      city: row.city || '',
      district: row.district || '',
      formatted_address: row.formatted_address || '',
      coord_count: row.coord_count || 0,
    }
  } else {
    form.value = {
      coords: row.coords,
      old_location: row.location,
      location: row.location,
      province: row.province || '',
      city: row.city || '',
      district: row.district || '',
      formatted_address: row.formatted_address || '',
      coord_count: 1,
    }
  }
  editVisible.value = true
  await loadSamples()
}

async function saveEdit() {
  if (!form.value.location.trim()) {
    ElMessage.warning('短地名不能为空')
    return
  }
  saving.value = true
  try {
    if (editMode.value === 'grouped') {
      const res = await axios.put('/api/geocode/cache/location', {
        old_location: form.value.old_location,
        new_location: form.value.location.trim(),
        province: form.value.province,
        city: form.value.city,
        district: form.value.district,
        formatted_address: form.value.formatted_address,
      })
      ElMessage.success(`已更新 ${res.data.updated} 条坐标映射`)
    } else {
      await axios.put('/api/geocode/cache/coords', {
        coords: form.value.coords,
        location: form.value.location.trim(),
        province: form.value.province,
        city: form.value.city,
        district: form.value.district,
        formatted_address: form.value.formatted_address,
      })
      ElMessage.success('已更新缓存')
    }
    editVisible.value = false
    await loadRegions()
    await loadStats()
    await loadData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function confirmDelete() {
  try {
    await ElMessageBox.confirm(
      `删除坐标 ${form.value.coords} 的缓存？regeocode 时会重新请求高德。`,
      '确认删除',
      { type: 'warning' }
    )
    await axios.delete('/api/geocode/cache/coords', { params: { coords: form.value.coords } })
    ElMessage.success('已删除')
    editVisible.value = false
    await loadRegions()
    await loadStats()
    await loadData()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  }
}

onMounted(async () => {
  await loadRegions()
  await loadStats()
  await loadData()
})
</script>

<style scoped>
.cache-container {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-x: hidden;
  overflow-y: auto;
  padding-bottom: 24px;
}

.cache-header {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.stats-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.hint {
  color: var(--muted);
  font-size: 0.85rem;
  margin-left: 0.5rem;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
}

.region-select {
  width: 180px;
}

.sort-select {
  width: 130px;
}

.search-input {
  flex: 1;
  min-width: 200px;
  max-width: 360px;
}

.cache-table {
  width: 100%;
}

.cache-table :deep(tr:hover) .location-name,
.cache-table :deep(tr:hover) .cell-strong,
.cache-table :deep(tr:hover) .cell-text,
.cache-table :deep(tr:hover) .cell-mono,
.cache-table :deep(tr:hover) .cell-warn {
  color: #ffffff !important;
}

.cache-table :deep(tr:hover) .cell-warn {
  color: #ffe0a3 !important;
}

.pager {
  display: flex;
  justify-content: flex-end;
}

.warn-text,
.cell-warn {
  color: #f3c27a;
}

.cell-region {
  color: #b8c9dc;
  font-weight: 600;
}

.cell-text {
  color: #d8e0ea;
}

.cell-strong {
  color: #ffffff;
  font-weight: 700;
  font-size: 0.95rem;
}

.cell-mono {
  color: #c8d4e3;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85rem;
}

.location-name {
  color: #ffffff;
  font-weight: 700;
  font-size: 1rem;
}

.edit-hint {
  margin: 0;
  font-size: 0.85rem;
  color: var(--muted);
}

.cache-edit-form :deep(.el-form-item__label) {
  color: var(--text-strong) !important;
  font-weight: 600;
}

.cache-edit-form :deep(.el-input__inner),
.cache-edit-form :deep(.el-textarea__inner) {
  color: var(--text-strong) !important;
}

.cache-edit-form :deep(.el-input.is-disabled .el-input__inner) {
  color: #c5d0de !important;
  -webkit-text-fill-color: #c5d0de;
}

.sample-section {
  margin-bottom: 1rem;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  min-height: 120px;
}

.sample-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.35rem;
}

.sample-title {
  font-weight: 600;
  color: var(--text-strong);
}

.sample-meta {
  font-size: 0.82rem;
  color: var(--muted);
}

.sample-hint {
  margin: 0 0 0.65rem;
  font-size: 0.82rem;
  color: var(--muted);
}

.sample-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.65rem;
}

.sample-card {
  cursor: pointer;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--panel);
  transition: border-color 0.15s ease;
}

.sample-card:hover {
  border-color: var(--accent);
}

.sample-thumb-wrap {
  aspect-ratio: 1;
  background: #243044;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sample-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.sample-no-image {
  color: var(--muted);
  font-size: 0.8rem;
}

.sample-caption {
  padding: 0.35rem 0.45rem 0.45rem;
  font-size: 0.75rem;
  line-height: 1.35;
}

.sample-time {
  color: var(--text-strong);
  font-weight: 600;
}

.sample-loc {
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sample-coords {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.68rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
