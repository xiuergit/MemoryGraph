<template>
  <div class="events-container">
    <header class="events-top">
      <div class="top-row">
        <el-radio-group v-model="viewMode" size="small" @change="onViewModeChange">
          <el-radio-button value="outings">出门</el-radio-button>
          <el-radio-button value="stories">故事</el-radio-button>
        </el-radio-group>
        <el-button size="small" :loading="syncing" @click="syncEvents">重建事件</el-button>
        <el-switch
          v-if="viewMode === 'outings'"
          v-model="includeHome"
          size="small"
          inline-prompt
          active-text="含家"
          inactive-text="出门"
          @change="reloadList"
        />
        <el-button
          v-if="viewMode === 'stories'"
          size="small"
          type="primary"
          @click="openNewStory"
        >
          新建故事
        </el-button>
        <span v-if="stats && viewMode === 'outings'" class="stats-inline">
          outing {{ stats.outing_events }} · 家 {{ stats.home_events }} · 覆盖
          {{ stats.coverage_pct }}%
          <template v-if="stats.orphan_overlays"> · 待认领 {{ stats.orphan_overlays }}</template>
        </span>
      </div>

      <div v-if="viewMode === 'outings'" class="filter-row">
        <el-select
          v-model="yearFilter"
          placeholder="年"
          clearable
          size="small"
          class="year-select"
          @change="onFilterChange"
        >
          <el-option v-for="y in years" :key="y" :label="`${y} 年`" :value="y" />
        </el-select>
        <el-date-picker
          v-model="monthFilter"
          type="month"
          placeholder="月"
          size="small"
          value-format="YYYY-MM"
          clearable
          class="month-picker"
          @change="onFilterChange"
        />
        <el-date-picker
          v-model="dayFilter"
          type="date"
          placeholder="日"
          size="small"
          value-format="YYYY-MM-DD"
          clearable
          class="day-picker"
          @change="onFilterChange"
        />
        <el-select
          v-model="personFilter"
          placeholder="人物"
          clearable
          filterable
          size="small"
          class="person-select"
          @change="onFilterChange"
        >
          <el-option
            v-for="p in registryPeople"
            :key="p.person_id"
            :label="p.name"
            :value="p.name"
          />
        </el-select>
        <el-select-v2
          v-model="locationFilter"
          placeholder="地点"
          clearable
          filterable
          size="small"
          class="location-select"
          :options="locationOptions"
          @change="onFilterChange"
        />
        <el-input
          v-model="keywordFilter"
          placeholder="场景/动作/物体，如 哭、爬、平衡车"
          clearable
          size="small"
          class="keyword-input"
          @change="onFilterChange"
          @keyup.enter="onFilterChange"
        />
        <span class="stats-inline">
          {{ events.length }} / {{ listTotal }}
        </span>
      </div>
    </header>

    <div class="events-body">
      <!-- 出门：宽表 + 右详情 -->
      <template v-if="viewMode === 'outings'">
        <div class="table-pane" v-loading="listLoading">
          <el-table
            :data="events"
            stripe
            size="small"
            height="100%"
            highlight-current-row
            :row-class-name="outingRowClass"
            @row-click="(row) => selectEvent(row.event_id)"
          >
            <el-table-column prop="day" label="日期" width="110" sortable />
            <el-table-column label="标题 / 地点" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.display_title }}
                <el-tag v-if="row.is_home" size="small" type="info" class="home-tag">家</el-tag>
                <el-tag v-if="row.overlay?.title" size="small" type="success" class="home-tag">
                  有备注
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="photo_count" label="张数" width="72" align="right" />
            <el-table-column label="人物" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                {{ (row.people || []).join('、') || '—' }}
              </template>
            </el-table-column>
            <el-table-column label="时段" width="150" show-overflow-tooltip>
              <template #default="{ row }">
                {{ shortTime(row.time_start) }}–{{ shortTime(row.time_end) }}
              </template>
            </el-table-column>
          </el-table>
          <div v-if="events.length < listTotal" class="table-footer">
            <el-button size="small" :loading="listLoading" @click="loadMore">
              加载更多
            </el-button>
          </div>
          <el-empty
            v-if="!listLoading && !events.length"
            description="暂无事件，点重建或放宽筛选"
          />
        </div>

        <aside class="detail-pane" v-loading="detailLoading">
          <template v-if="mode === 'event' && detail">
            <header class="detail-head">
              <h2>{{ detail.display_title }}</h2>
              <p class="muted">
                {{ detail.day }} · {{ detail.photo_count }} 张
                <span v-if="detail.is_home"> · 家</span>
              </p>
              <p v-if="detail.people?.length" class="muted">
                {{ detail.people.join('、') }}
              </p>
            </header>

            <section class="overlay-editor">
              <h3>补意义</h3>
              <el-input v-model="overlayTitle" placeholder="标题，如：公园轮滑" class="mb" size="small" />
              <el-input
                v-model="overlayBody"
                type="textarea"
                :rows="4"
                placeholder="照片说不清的事…"
              />
              <div class="overlay-actions">
                <el-button type="primary" size="small" :loading="savingOverlay" @click="saveOverlay">
                  保存备注
                </el-button>
                <el-button
                  v-if="detail.overlay"
                  size="small"
                  :loading="savingOverlay"
                  @click="clearOverlay"
                >
                  清除
                </el-button>
                <el-button size="small" @click="promoteToStory">做成故事</el-button>
              </div>
            </section>

            <section class="photo-section">
              <div class="photo-head">
                <h3>照片 · {{ detail.photos?.length || 0 }}</h3>
                <span class="muted photo-select-hint">点图多选 · 改 JSON 地址</span>
              </div>

              <div v-if="photoLocationGroups.length" class="loc-chips">
                <button
                  v-for="g in photoLocationGroups"
                  :key="g.key"
                  type="button"
                  class="loc-chip"
                  :class="{ active: isGroupFullySelected(g) }"
                  :title="g.label"
                  @click="toggleSelectByLocation(g.key)"
                >
                  {{ g.label }} ×{{ g.count }}
                </button>
              </div>

              <div class="batch-bar">
                <span class="batch-count">已选 {{ selectedPhotoIds.length }}</span>
                <el-button size="small" @click="selectAllPhotos">全选</el-button>
                <el-button
                  size="small"
                  :disabled="!selectedPhotoIds.length"
                  @click="clearPhotoSelection"
                >
                  取消
                </el-button>
                <el-button
                  type="primary"
                  size="small"
                  :disabled="!selectedPhotoIds.length"
                  @click="openLocationDialog"
                >
                  批量改地址
                </el-button>
              </div>

              <div class="photo-grid">
                <div
                  v-for="photo in detail.photos || []"
                  :key="photo.photo_id"
                  class="photo-card"
                  :class="{ selected: isPhotoSelected(photo.photo_id) }"
                >
                  <button
                    type="button"
                    class="photo-thumb"
                    @click="togglePhotoSelect(photo.photo_id)"
                  >
                    <img
                      v-if="photo.source_path"
                      :src="previewUrl(photo.source_path)"
                      :alt="photo.photo_id"
                      loading="lazy"
                    />
                    <div v-else class="photo-placeholder">无预览</div>
                  </button>
                  <div class="photo-meta" :title="photo.location || '无地址'">
                    {{ photo.location || '无地址' }}
                  </div>
                  <button
                    type="button"
                    class="photo-detail-link"
                    @click.stop="emit('view-detail', photo.photo_id)"
                  >
                    详情
                  </button>
                </div>
              </div>
            </section>
          </template>
          <div v-else class="empty-detail">
            <el-empty description="点表格一行查看详情与备注" :image-size="72" />
          </div>
        </aside>
      </template>

      <!-- 故事：宽表 + 右编辑 -->
      <template v-else>
        <div class="table-pane" v-loading="listLoading">
          <el-table
            :data="stories"
            stripe
            size="small"
            height="100%"
            highlight-current-row
            :row-class-name="storyRowClass"
            @row-click="(row) => selectStory(row.story_id)"
          >
            <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
            <el-table-column prop="link_count" label="关联" width="72" align="right" />
            <el-table-column prop="updated_at" label="更新" width="170" show-overflow-tooltip />
            <el-table-column label="摘要" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                {{ (row.body || '').slice(0, 80) }}
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!stories.length" description="还没有跨天故事，可点新建或从出门「做成故事」" />
        </div>

        <aside class="detail-pane" v-loading="detailLoading">
          <template v-if="mode === 'story' && storyDetail">
            <header class="detail-head">
              <h2>{{ storyDetail.story_id === 'new' ? '新建故事' : '编辑故事' }}</h2>
            </header>
            <section class="overlay-editor">
              <el-input v-model="storyTitle" placeholder="标题，如：第一次轮滑" class="mb" />
              <el-input
                v-model="storyBody"
                type="textarea"
                :rows="12"
                placeholder="长叙事：想买鞋 → 爸爸不让 → 还是买了 → 帽子丢了…"
              />
              <div class="overlay-actions">
                <el-button type="primary" size="small" :loading="savingStory" @click="saveStory">
                  保存
                </el-button>
                <el-button
                  v-if="storyDetail.story_id && storyDetail.story_id !== 'new'"
                  type="danger"
                  plain
                  size="small"
                  :loading="savingStory"
                  @click="removeStory"
                >
                  删除
                </el-button>
              </div>
              <div v-if="storyDetail.links?.length" class="links-box">
                <h4>已关联</h4>
                <div v-for="(l, i) in storyDetail.links" :key="i" class="link-row">
                  <el-tag size="small">{{ l.link_type }}</el-tag>
                  <span class="link-id">{{ l.link_id }}</span>
                  <el-button
                    v-if="l.link_type === 'event'"
                    link
                    type="primary"
                    @click="openEventFromStory(l.link_id)"
                  >
                    打开事件
                  </el-button>
                </div>
              </div>
            </section>
          </template>
          <div v-else class="empty-detail">
            <el-empty description="选择故事或点新建" :image-size="72" />
          </div>
        </aside>
      </template>
    </div>

    <el-dialog v-model="locationDialogVisible" title="批量改地址" width="520px" destroy-on-close>
      <p class="dialog-hint">
        将写入选中 {{ selectedPhotoIds.length }} 张照片的 location，并标记 manual_location。
        事件是派生数据，改完后建议重建事件。
      </p>
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
        <el-button type="primary" :loading="batchSaving" @click="submitBatchLocation">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const emit = defineEmits(['view-detail'])

const viewMode = ref('outings') // outings | stories
const includeHome = ref(false)
const yearFilter = ref('')
const monthFilter = ref('')
const dayFilter = ref('')
const locationFilter = ref('')
const keywordFilter = ref('')
const personFilter = ref('')
const years = ref([])
const eventLocations = ref([])
const locationItems = ref([])
const registryPeople = ref([])
const listLoading = ref(false)
const detailLoading = ref(false)
const syncing = ref(false)
const events = ref([])
const listTotal = ref(0)
const selectedPhotoIds = ref([])
const locationDialogVisible = ref(false)
const batchSaving = ref(false)
const batchLocation = ref('')
const batchProvince = ref('')
const batchCity = ref('')
const batchDistrict = ref('')
const batchFormattedAddress = ref('')
const pageSize = 50
const stories = ref([])
const stats = ref(null)
const selectedId = ref('')
const selectedStoryId = ref('')
const detail = ref(null)
const storyDetail = ref(null)
const mode = ref('event') // event | story

const overlayTitle = ref('')
const overlayBody = ref('')
const savingOverlay = ref(false)

const storyTitle = ref('')
const storyBody = ref('')
const savingStory = ref(false)

const locationOptions = computed(() =>
  (eventLocations.value || []).map((item) => ({
    value: item.location,
    label: `${item.location} (${item.count})`,
  })),
)

const photoLocationGroups = computed(() => {
  const counts = new Map()
  for (const photo of detail.value?.photos || []) {
    const key = (photo.location || '').trim()
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([key, count]) => ({
      key,
      label: key || '无地址',
      count,
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'zh'))
})

function previewUrl(path) {
  return `/api/preview?path=${encodeURIComponent(path)}&size=640`
}

function shortTime(timestamp) {
  if (!timestamp || timestamp.length < 16) return timestamp || '—'
  return timestamp.slice(11, 16)
}

function isPhotoSelected(photoId) {
  return selectedPhotoIds.value.includes(photoId)
}

function togglePhotoSelect(photoId) {
  if (isPhotoSelected(photoId)) {
    selectedPhotoIds.value = selectedPhotoIds.value.filter((id) => id !== photoId)
  } else {
    selectedPhotoIds.value = [...selectedPhotoIds.value, photoId]
  }
}

function clearPhotoSelection() {
  selectedPhotoIds.value = []
}

function selectAllPhotos() {
  selectedPhotoIds.value = (detail.value?.photos || []).map((p) => p.photo_id).filter(Boolean)
}

function photosWithLocationKey(key) {
  return (detail.value?.photos || []).filter((p) => (p.location || '').trim() === key)
}

function isGroupFullySelected(group) {
  const ids = photosWithLocationKey(group.key).map((p) => p.photo_id)
  return ids.length > 0 && ids.every((id) => isPhotoSelected(id))
}

function toggleSelectByLocation(key) {
  const ids = photosWithLocationKey(key).map((p) => p.photo_id)
  if (!ids.length) return
  if (ids.every((id) => isPhotoSelected(id))) {
    selectedPhotoIds.value = selectedPhotoIds.value.filter((id) => !ids.includes(id))
  } else {
    const set = new Set(selectedPhotoIds.value)
    ids.forEach((id) => set.add(id))
    selectedPhotoIds.value = [...set]
  }
}

async function loadMemoryLocations() {
  try {
    const res = await axios.get('/api/memory/locations')
    locationItems.value = res.data.items || []
  } catch {
    locationItems.value = []
  }
}

function openLocationDialog() {
  if (!selectedPhotoIds.value.length) {
    ElMessage.warning('请先选择照片')
    return
  }
  batchLocation.value = ''
  batchProvince.value = ''
  batchCity.value = ''
  batchDistrict.value = ''
  batchFormattedAddress.value = ''
  locationDialogVisible.value = true
}

function onBatchLocationChange(loc) {
  const item = locationItems.value.find((entry) => entry.location === loc)
  if (!item) return
  batchProvince.value = item.province || ''
  batchCity.value = item.city || ''
  batchDistrict.value = item.district || ''
  batchFormattedAddress.value = item.formatted_address || item.location || ''
}

async function submitBatchLocation() {
  const ids = [...selectedPhotoIds.value]
  if (!ids.length) {
    ElMessage.warning('请先选择照片')
    return
  }
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
    const { updated, failed_count: failedCount, failed } = res.data
    if (failedCount > 0) {
      const detailText = (failed || [])
        .map((item) => `${item.photo_id}: ${item.error}`)
        .join('\n')
      ElMessage.warning(`已更新 ${updated} 条，失败 ${failedCount} 条\n${detailText}`)
    } else {
      ElMessage.success(`已更新 ${updated} 条 JSON`)
    }
    locationDialogVisible.value = false
    clearPhotoSelection()
    if (selectedId.value) await selectEvent(selectedId.value)
    await loadMemoryLocations()
    try {
      await ElMessageBox.confirm(
        '地址已写入照片 JSON。事件是派生数据，是否现在重建事件？',
        '重建事件',
        { confirmButtonText: '重建', cancelButtonText: '稍后', type: 'info' },
      )
      await syncEvents()
    } catch {
      /* 用户取消 */
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '批量改地址失败')
  } finally {
    batchSaving.value = false
  }
}

function dayQuery() {
  if (dayFilter.value) return dayFilter.value
  if (monthFilter.value) return monthFilter.value
  if (yearFilter.value) return String(yearFilter.value)
  return ''
}

function listParams(offset = 0) {
  return {
    include_home: includeHome.value,
    day: dayQuery() || undefined,
    location: locationFilter.value.trim() || undefined,
    person: personFilter.value.trim() || undefined,
    keyword: keywordFilter.value.trim() || undefined,
    limit: pageSize,
    offset,
  }
}

function outingRowClass({ row }) {
  return row.event_id === selectedId.value ? 'is-selected-row' : ''
}

function storyRowClass({ row }) {
  return row.story_id === selectedStoryId.value ? 'is-selected-row' : ''
}

function onViewModeChange() {
  if (viewMode.value === 'outings') {
    mode.value = 'event'
    selectedStoryId.value = ''
    storyDetail.value = null
  } else {
    mode.value = 'story'
    selectedId.value = ''
    detail.value = null
  }
}

async function loadStats() {
  const res = await axios.get('/api/events/stats')
  stats.value = res.data
}

async function loadYears() {
  try {
    const res = await axios.get('/api/events/years', {
      params: { include_home: true },
    })
    years.value = res.data.years || []
  } catch {
    years.value = []
  }
}

async function loadEventLocations() {
  try {
    const res = await axios.get('/api/events/locations', {
      params: { include_home: true },
    })
    eventLocations.value = res.data.items || []
  } catch {
    eventLocations.value = []
  }
}

async function loadRegistryPeople() {
  try {
    const res = await axios.get('/api/face/registry')
    const people = res.data.people || res.data || []
    registryPeople.value = Array.isArray(people)
      ? people.filter((p) => p.name && !String(p.name).startsWith('unk_'))
      : []
  } catch {
    registryPeople.value = []
  }
}

function onFilterChange() {
  reloadList()
}

async function reloadList() {
  listLoading.value = true
  try {
    const res = await axios.get('/api/events', { params: listParams(0) })
    events.value = res.data.items || []
    listTotal.value = res.data.total || 0
    await loadStats()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '加载事件失败')
  } finally {
    listLoading.value = false
  }
}

async function loadMore() {
  if (events.value.length >= listTotal.value) return
  listLoading.value = true
  try {
    const res = await axios.get('/api/events', {
      params: listParams(events.value.length),
    })
    const more = res.data.items || []
    events.value = events.value.concat(more)
    listTotal.value = res.data.total || listTotal.value
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '加载更多失败')
  } finally {
    listLoading.value = false
  }
}

async function loadStories() {
  try {
    const res = await axios.get('/api/stories', { params: { limit: 100 } })
    stories.value = res.data.items || []
  } catch {
    stories.value = []
  }
}

async function syncEvents() {
  syncing.value = true
  try {
    const res = await axios.post('/api/events/sync')
    ElMessage.success(
      `已重建：outing ${res.data.outing_events} / 家 ${res.data.home_events}`,
    )
    await loadYears()
    await loadEventLocations()
    await reloadList()
    if (selectedId.value) await selectEvent(selectedId.value)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '重建失败')
  } finally {
    syncing.value = false
  }
}

async function selectEvent(eventId) {
  viewMode.value = 'outings'
  mode.value = 'event'
  selectedId.value = eventId
  selectedStoryId.value = ''
  storyDetail.value = null
  clearPhotoSelection()
  detailLoading.value = true
  try {
    const res = await axios.get(`/api/events/${encodeURIComponent(eventId)}`)
    detail.value = res.data
    overlayTitle.value = res.data.overlay?.title || ''
    overlayBody.value = res.data.overlay?.body || ''
  } catch (err) {
    detail.value = null
    ElMessage.error(err.response?.data?.detail || '加载详情失败')
  } finally {
    detailLoading.value = false
  }
}

function openEventFromStory(eventId) {
  viewMode.value = 'outings'
  selectEvent(eventId)
}

async function saveOverlay() {
  if (!selectedId.value) return
  savingOverlay.value = true
  try {
    await axios.put(`/api/events/${encodeURIComponent(selectedId.value)}/overlay`, {
      title: overlayTitle.value,
      body: overlayBody.value,
      tags: [],
    })
    ElMessage.success('备注已保存')
    await selectEvent(selectedId.value)
    await reloadList()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '保存失败')
  } finally {
    savingOverlay.value = false
  }
}

async function clearOverlay() {
  if (!selectedId.value) return
  try {
    await ElMessageBox.confirm('清除本趟备注？', '确认')
  } catch {
    return
  }
  savingOverlay.value = true
  try {
    await axios.delete(`/api/events/${encodeURIComponent(selectedId.value)}/overlay`)
    overlayTitle.value = ''
    overlayBody.value = ''
    ElMessage.success('已清除')
    await selectEvent(selectedId.value)
    await reloadList()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '清除失败')
  } finally {
    savingOverlay.value = false
  }
}

function openNewStory() {
  viewMode.value = 'stories'
  mode.value = 'story'
  selectedStoryId.value = 'new'
  selectedId.value = ''
  detail.value = null
  storyDetail.value = {
    story_id: 'new',
    title: '',
    body: '',
    links: [],
  }
  storyTitle.value = ''
  storyBody.value = ''
}

async function selectStory(storyId) {
  viewMode.value = 'stories'
  mode.value = 'story'
  selectedStoryId.value = storyId
  selectedId.value = ''
  detail.value = null
  detailLoading.value = true
  try {
    const res = await axios.get(`/api/stories/${encodeURIComponent(storyId)}`)
    storyDetail.value = res.data
    storyTitle.value = res.data.title || ''
    storyBody.value = res.data.body || ''
  } catch (err) {
    storyDetail.value = null
    ElMessage.error(err.response?.data?.detail || '加载故事失败')
  } finally {
    detailLoading.value = false
  }
}

async function promoteToStory() {
  if (!detail.value) return
  const defaultTitle =
    overlayTitle.value.trim() ||
    detail.value.display_title ||
    `${detail.value.day} · ${detail.value.location}`
  viewMode.value = 'stories'
  mode.value = 'story'
  selectedStoryId.value = 'new'
  storyDetail.value = {
    story_id: 'new',
    title: defaultTitle,
    body: overlayBody.value,
    links: [{ link_type: 'event', link_id: detail.value.event_id, sort_order: 0 }],
  }
  storyTitle.value = defaultTitle
  storyBody.value = overlayBody.value
}

async function saveStory() {
  if (!storyTitle.value.trim()) {
    ElMessage.warning('请填写故事标题')
    return
  }
  savingStory.value = true
  try {
    const links = storyDetail.value?.links || []
    if (!storyDetail.value?.story_id || storyDetail.value.story_id === 'new') {
      const res = await axios.post('/api/stories', {
        title: storyTitle.value,
        body: storyBody.value,
        links,
      })
      ElMessage.success('故事已创建')
      await loadStories()
      await selectStory(res.data.story.story_id)
    } else {
      await axios.put(`/api/stories/${encodeURIComponent(storyDetail.value.story_id)}`, {
        title: storyTitle.value,
        body: storyBody.value,
        links,
      })
      ElMessage.success('故事已保存')
      await loadStories()
      await selectStory(storyDetail.value.story_id)
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '保存故事失败')
  } finally {
    savingStory.value = false
  }
}

async function removeStory() {
  if (!storyDetail.value?.story_id || storyDetail.value.story_id === 'new') return
  try {
    await ElMessageBox.confirm('删除该故事？', '确认')
  } catch {
    return
  }
  savingStory.value = true
  try {
    await axios.delete(`/api/stories/${encodeURIComponent(storyDetail.value.story_id)}`)
    ElMessage.success('已删除')
    storyDetail.value = null
    selectedStoryId.value = ''
    mode.value = 'event'
    await loadStories()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
  } finally {
    savingStory.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    loadYears(),
    loadRegistryPeople(),
    loadEventLocations(),
    loadMemoryLocations(),
  ])
  await reloadList()
  await loadStories()
})
</script>

<style scoped>
.events-container {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  overflow: hidden;
}

.events-top {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.top-row,
.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.stats-inline {
  font-size: 0.78rem;
  color: var(--muted);
  margin-left: 0.25rem;
}

.year-select {
  width: 100px;
}

.month-picker,
.day-picker {
  width: 130px;
}

.person-select {
  width: 140px;
}

.location-select {
  width: 220px;
}

.keyword-input {
  width: 220px;
}

.events-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 0.85rem;
  overflow: hidden;
}

.table-pane {
  flex: 1 1 42%;
  min-width: 280px;
  max-width: 52%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
}

.table-pane :deep(.el-table) {
  flex: 1;
}

.table-pane :deep(.is-selected-row) {
  --el-table-tr-bg-color: rgba(91, 159, 212, 0.12);
}

.table-pane :deep(.el-table__row) {
  cursor: pointer;
}

.table-footer {
  flex-shrink: 0;
  padding: 0.45rem 0.65rem;
  border-top: 1px solid var(--border);
}

.home-tag {
  margin-left: 0.35rem;
  vertical-align: middle;
}

.detail-pane {
  flex: 1 1 48%;
  min-width: 420px;
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-2);
  padding: 0.85rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.empty-detail {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.detail-head h2 {
  margin: 0 0 0.35rem;
  font-size: 1.05rem;
  line-height: 1.35;
}

.detail-head p {
  margin: 0.15rem 0;
  font-size: 0.85rem;
}

.addr-hint {
  margin-top: 0.45rem !important;
  font-size: 0.75rem !important;
  line-height: 1.4;
}

.muted {
  color: var(--muted);
}

.overlay-editor h3,
.photo-section h3 {
  margin: 0;
  font-size: 0.9rem;
}

.photo-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.45rem;
}

.photo-select-hint {
  font-size: 0.72rem;
  flex-shrink: 0;
}

.loc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 0.45rem;
}

.loc-chip {
  max-width: 100%;
  padding: 0.15rem 0.45rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel);
  color: var(--text);
  font-size: 0.72rem;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.loc-chip.active {
  border-color: rgba(91, 159, 212, 0.85);
  background: rgba(91, 159, 212, 0.18);
}

.batch-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.55rem;
}

.batch-count {
  font-size: 0.78rem;
  color: var(--muted);
  margin-right: 0.15rem;
}

.dialog-hint {
  margin: 0 0 0.85rem;
  font-size: 0.82rem;
  color: var(--muted);
  line-height: 1.45;
}

.mb {
  margin-bottom: 0.45rem;
}

.overlay-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.55rem;
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
  gap: 0.5rem;
}

.photo-card {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 5px;
  overflow: hidden;
  background: #121820;
}

.photo-card.selected {
  border-color: rgba(91, 159, 212, 0.95);
  box-shadow: 0 0 0 1px rgba(91, 159, 212, 0.55);
}

.photo-thumb {
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  display: block;
  width: 100%;
}

.photo-card img,
.photo-placeholder {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
}

.photo-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.65rem;
  color: var(--muted);
}

.photo-meta {
  padding: 0.2rem 0.3rem 0;
  font-size: 0.65rem;
  line-height: 1.25;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.photo-detail-link {
  padding: 0.15rem 0.3rem 0.3rem;
  border: none;
  background: transparent;
  color: #7eb6e8;
  font-size: 0.68rem;
  cursor: pointer;
  text-align: left;
}

.photo-detail-link:hover {
  text-decoration: underline;
}

.links-box {
  margin-top: 0.85rem;
}

.links-box h4 {
  margin: 0 0 0.35rem;
  font-size: 0.85rem;
}

.link-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.3rem;
  font-size: 0.8rem;
}

.link-id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}

@media (max-width: 960px) {
  .events-body {
    flex-direction: column;
  }

  .table-pane {
    max-width: none;
  }

  .detail-pane {
    flex: 0 0 auto;
    min-width: 0;
    max-height: 45%;
  }
}
</style>
