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
          outing {{ stats.outing_events }} · 家 {{ stats.home_events }}
          <template v-if="stats.untimed_location_events">
            · 无时间地点 {{ stats.untimed_location_events }}
          </template>
          · 覆盖 {{ stats.coverage_pct }}%
          <template v-if="stats.orphan_overlays"> · 待认领 {{ stats.orphan_overlays }}</template>
        </span>
      </div>

      <div v-if="viewMode === 'outings'" class="filter-row">
        <el-select
          v-model="timeScope"
          size="small"
          class="time-scope-select"
          @change="onTimeScopeChange"
        >
          <el-option label="全部时间" value="all" />
          <el-option label="有日期" value="dated" />
          <el-option label="无时间地点" value="untimed" />
        </el-select>
        <el-select
          v-model="yearFilter"
          placeholder="年"
          clearable
          size="small"
          class="year-select"
          :disabled="timeScope === 'untimed'"
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
          :disabled="timeScope === 'untimed'"
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
          :disabled="timeScope === 'untimed'"
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
            <el-table-column label="日期" width="110" sortable prop="day">
              <template #default="{ row }">{{ dayLabel(row.day) }}</template>
            </el-table-column>
            <el-table-column label="标题 / 地点" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.display_title }}
                <el-tag v-if="row.is_home" size="small" type="info" class="home-tag">家</el-tag>
                <el-tag
                  v-if="row.source === 'untimed_loc'"
                  size="small"
                  type="warning"
                  class="home-tag"
                >
                  无时间
                </el-tag>
                <el-tag v-if="row.overlay?.title" size="small" type="success" class="home-tag">
                  有备注
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="天气" width="148" show-overflow-tooltip>
              <template #default="{ row }">
                <span :class="{ 'weather-empty': !row.weather_label }">
                  {{ row.weather_label || '—' }}
                </span>
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
                <template v-if="row.source === 'untimed_loc'">按地点聚合</template>
                <template v-else>
                  {{ shortTime(row.time_start) }}–{{ shortTime(row.time_end) }}
                </template>
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
                {{ dayLabel(detail.day) }} · {{ detail.photo_count }} 张
                <span v-if="detail.is_home"> · 家</span>
                <span v-if="detail.source === 'untimed_loc'"> · 无时间按地点</span>
              </p>
              <p v-if="detail.weather_label" class="muted weather-line">
                {{ detail.weather_label }}
              </p>
              <p v-if="detail.people?.length" class="muted">
                {{ detail.people.join('、') }}
              </p>
            </header>

            <section class="overlay-editor">
              <h3>补意义</h3>
              <p class="section-hint">
                单次出门的短说明写这里。若叙事跨多天、跨多次出门，保存后点「做成故事」。
              </p>
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
                <h3>
                  媒体 · {{ detail.photos?.length || 0 }}
                  <template v-if="eventVideoCount">
                    <span class="muted">（视频 {{ eventVideoCount }}）</span>
                  </template>
                </h3>
                <span class="muted photo-select-hint">点图多选 · 改地址 / 删除</span>
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
                <el-button
                  type="success"
                  size="small"
                  plain
                  :disabled="!selectedPhotoIds.length"
                  :loading="sendingPrint"
                  @click="sendToPaperCut"
                >
                  送到剪纸排版
                </el-button>
                <el-button
                  type="primary"
                  size="small"
                  plain
                  :disabled="!selectedPhotoIds.length || selectedPhotoIds.length !== 6"
                  :loading="sendingStory"
                  @click="sendToStoryCircle"
                >
                  做成分享页
                </el-button>
                <el-button
                  type="danger"
                  size="small"
                  :disabled="!selectedPhotoIds.length"
                  :loading="deletingPhotos"
                  @click="deleteSelectedPhotos"
                >
                  删除选中
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
                    <span
                      v-if="photo.media_type === 'video'"
                      class="media-badge"
                    >视频</span>
                    <span
                      v-else-if="photo.media_type === 'audio'"
                      class="media-badge audio"
                    >音频</span>
                  </button>
                  <div class="photo-meta" :title="photo.location || '无地址'">
                    {{ photo.location || '无地址' }}
                  </div>
                  <div class="photo-card-actions">
                    <button
                      type="button"
                      class="photo-detail-link"
                      @click.stop="emit('view-detail', photo.photo_id)"
                    >
                      详情
                    </button>
                    <button
                      type="button"
                      class="photo-delete-link"
                      :disabled="deletingPhotos"
                      @click.stop="deleteOnePhoto(photo.photo_id)"
                    >
                      删除
                    </button>
                  </div>
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
            <section class="overlay-editor story-editor">
              <el-input v-model="storyTitle" placeholder="标题，如：第一次轮滑" class="mb" />
              <el-input
                v-model="storyBody"
                type="textarea"
                :rows="10"
                placeholder="长叙事：想买鞋 → 爸爸不让 → 还是买了 → 帽子丢了…"
              />
              <div class="overlay-actions">
                <el-button type="primary" size="small" :loading="savingStory" @click="saveStory">
                  保存故事
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

              <section class="links-box">
                <div class="links-head">
                  <h4>关联出门</h4>
                  <el-button size="small" type="primary" plain @click="openLinkPicker">
                    添加出门
                  </el-button>
                </div>
                <p class="section-hint">
                  把故事锚定到具体几次出门；问答「……的故事」会用到这些关联。
                </p>
                <div v-if="sortedEventLinks.length" class="link-cards">
                  <div
                    v-for="(link, index) in sortedEventLinks"
                    :key="`${link.link_id}-${index}`"
                    class="link-card"
                  >
                    <div class="link-card-main">
                      <div class="link-card-title">
                        {{ linkSummary(link.link_id)?.display_title || link.link_id }}
                        <el-tag v-if="linkSummary(link.link_id)?.is_home" size="small" type="info">
                          家
                        </el-tag>
                      </div>
                      <div class="link-card-meta muted">
                        {{ linkSummary(link.link_id)?.day || '—' }}
                        · {{ linkSummary(link.link_id)?.photo_count ?? '—' }} 张
                        <span v-if="linkSummary(link.link_id)?.location">
                          · {{ linkSummary(link.link_id).location }}
                        </span>
                      </div>
                    </div>
                    <div class="link-card-actions">
                      <el-button link type="primary" size="small" @click="openEventFromStory(link.link_id)">
                        打开
                      </el-button>
                      <el-button link type="danger" size="small" @click="removeStoryEventLink(link.link_id)">
                        移除
                      </el-button>
                    </div>
                  </div>
                </div>
                <el-empty
                  v-else
                  :image-size="56"
                  description="还没有关联出门，点「添加出门」搜索并加入"
                />
              </section>
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

    <el-dialog
      v-model="linkPickerVisible"
      title="添加关联出门"
      width="720px"
      destroy-on-close
      @opened="onLinkPickerOpened"
    >
      <p class="dialog-hint">
        按日期、人物、地点或关键词筛选，点「添加」挂到当前故事。已关联的出门会显示「已添加」。
      </p>
      <div class="link-picker-filters">
        <el-select
          v-model="linkPickerYear"
          placeholder="年"
          clearable
          size="small"
          class="year-select"
          @change="searchLinkPickerEvents"
        >
          <el-option v-for="y in years" :key="y" :label="`${y} 年`" :value="y" />
        </el-select>
        <el-select
          v-model="linkPickerPerson"
          placeholder="人物"
          clearable
          filterable
          size="small"
          class="person-select"
          @change="searchLinkPickerEvents"
        >
          <el-option
            v-for="p in registryPeople"
            :key="p.person_id"
            :label="p.name"
            :value="p.name"
          />
        </el-select>
        <el-select-v2
          v-model="linkPickerLocation"
          placeholder="地点"
          clearable
          filterable
          size="small"
          class="location-select"
          :options="locationOptions"
          @change="searchLinkPickerEvents"
        />
        <el-input
          v-model="linkPickerKeyword"
          placeholder="场景/动作，如 轮滑、哭"
          clearable
          size="small"
          class="keyword-input"
          @change="searchLinkPickerEvents"
          @keyup.enter="searchLinkPickerEvents"
        />
        <el-button size="small" :loading="linkPickerLoading" @click="searchLinkPickerEvents">
          搜索
        </el-button>
      </div>
      <el-table
        v-loading="linkPickerLoading"
        :data="linkPickerEvents"
        stripe
        size="small"
        max-height="360"
        empty-text="没有匹配的出门，试试放宽筛选"
      >
        <el-table-column prop="day" label="日期" width="110" />
        <el-table-column label="出门" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.display_title }}
            <el-tag v-if="row.is_home" size="small" type="info" class="home-tag">家</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="photo_count" label="张数" width="72" align="right" />
        <el-table-column label="人物" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            {{ (row.people || []).join('、') || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="" width="88" align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="isEventLinked(row.event_id)"
              size="small"
              disabled
            >
              已添加
            </el-button>
            <el-button
              v-else
              size="small"
              type="primary"
              link
              @click="addStoryEventLink(row)"
            >
              添加
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="linkPickerTotal > linkPickerEvents.length" class="dialog-footer-hint muted">
        仅显示前 {{ linkPickerEvents.length }} 条，共 {{ linkPickerTotal }} 条；请用筛选缩小范围。
      </div>
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
/** all | dated | untimed */
const timeScope = ref('all')
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
const deletingPhotos = ref(false)
const sendingPrint = ref(false)
const sendingStory = ref(false)
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
const storyLinkSummaries = ref({})

const linkPickerVisible = ref(false)
const linkPickerLoading = ref(false)
const linkPickerEvents = ref([])
const linkPickerTotal = ref(0)
const linkPickerYear = ref('')
const linkPickerPerson = ref('')
const linkPickerLocation = ref('')
const linkPickerKeyword = ref('')

const sortedEventLinks = computed(() => {
  const links = (storyDetail.value?.links || []).filter((l) => l.link_type === 'event')
  return [...links].sort((a, b) => {
    const dayA = storyLinkSummaries.value[a.link_id]?.day || ''
    const dayB = storyLinkSummaries.value[b.link_id]?.day || ''
    return dayA.localeCompare(dayB)
  })
})

function linkSummary(eventId) {
  return storyLinkSummaries.value[eventId] || null
}

function isEventLinked(eventId) {
  return (storyDetail.value?.links || []).some(
    (l) => l.link_type === 'event' && l.link_id === eventId,
  )
}

async function loadStoryLinkSummaries() {
  const links = storyDetail.value?.links || []
  const eventIds = links.filter((l) => l.link_type === 'event').map((l) => l.link_id)
  if (!eventIds.length) {
    storyLinkSummaries.value = {}
    return
  }
  const summaries = {}
  await Promise.all(
    eventIds.map(async (eventId) => {
      try {
        const res = await axios.get(`/api/events/${encodeURIComponent(eventId)}`)
        summaries[eventId] = {
          day: res.data.day,
          display_title: res.data.display_title,
          photo_count: res.data.photo_count,
          location: res.data.location,
          is_home: res.data.is_home,
        }
      } catch {
        summaries[eventId] = {
          display_title: eventId,
          missing: true,
        }
      }
    }),
  )
  storyLinkSummaries.value = summaries
}

function ensureStoryLinks() {
  if (!storyDetail.value) return
  if (!Array.isArray(storyDetail.value.links)) {
    storyDetail.value.links = []
  }
}

function addStoryEventLink(row) {
  if (!storyDetail.value || isEventLinked(row.event_id)) return
  ensureStoryLinks()
  const order = storyDetail.value.links.length
  storyDetail.value.links.push({
    link_type: 'event',
    link_id: row.event_id,
    sort_order: order,
  })
  storyLinkSummaries.value = {
    ...storyLinkSummaries.value,
    [row.event_id]: {
      day: row.day,
      display_title: row.display_title,
      photo_count: row.photo_count,
      location: row.location,
      is_home: row.is_home,
    },
  }
  ElMessage.success('已加入关联，记得点「保存故事」')
}

function removeStoryEventLink(eventId) {
  if (!storyDetail.value?.links) return
  storyDetail.value.links = storyDetail.value.links.filter(
    (l) => !(l.link_type === 'event' && l.link_id === eventId),
  )
  const next = { ...storyLinkSummaries.value }
  delete next[eventId]
  storyLinkSummaries.value = next
  ElMessage.success('已移除关联，记得点「保存故事」')
}

function openLinkPicker() {
  if (!storyDetail.value) {
    ElMessage.warning('请先选择或新建故事')
    return
  }
  linkPickerVisible.value = true
}

function onLinkPickerOpened() {
  linkPickerYear.value = ''
  linkPickerPerson.value = ''
  linkPickerLocation.value = ''
  linkPickerKeyword.value = ''
  searchLinkPickerEvents()
}

async function searchLinkPickerEvents() {
  linkPickerLoading.value = true
  try {
    const res = await axios.get('/api/events', {
      params: {
        include_home: true,
        day: linkPickerYear.value ? String(linkPickerYear.value) : undefined,
        person: linkPickerPerson.value.trim() || undefined,
        location: linkPickerLocation.value.trim() || undefined,
        keyword: linkPickerKeyword.value.trim() || undefined,
        limit: 80,
        offset: 0,
      },
    })
    linkPickerEvents.value = res.data.items || []
    linkPickerTotal.value = res.data.total || 0
  } catch (err) {
    linkPickerEvents.value = []
    linkPickerTotal.value = 0
    ElMessage.error(err.response?.data?.detail || '搜索出门失败')
  } finally {
    linkPickerLoading.value = false
  }
}

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

const eventVideoCount = computed(() =>
  (detail.value?.photos || []).filter((p) => p.media_type === 'video').length,
)

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

async function openLocationDialog() {
  if (!selectedPhotoIds.value.length) {
    ElMessage.warning('请先选择照片')
    return
  }
  batchLocation.value = ''
  batchProvince.value = ''
  batchCity.value = ''
  batchDistrict.value = ''
  batchFormattedAddress.value = ''
  await loadMemoryLocations()
  locationDialogVisible.value = true
}

async function promptRebuildAfterPhotoDelete() {
  try {
    await ElMessageBox.confirm(
      '照片已移入 data/.trash/。事件是派生数据，是否现在重建事件？',
      '重建事件',
      { confirmButtonText: '重建', cancelButtonText: '稍后', type: 'info' },
    )
    await syncEvents()
  } catch {
    /* 用户取消 */
  }
}

async function deletePhotosByIds(ids, { confirmTitle, confirmMsg } = {}) {
  const photoIds = (ids || []).filter(Boolean)
  if (!photoIds.length) return false

  try {
    await ElMessageBox.confirm(
      confirmMsg ||
        `确定删除选中的 ${photoIds.length} 张照片？\n\n原图 + memory JSON 会移入 data/.trash/\nSQLite 索引同步清除（无需再 sync）`,
      confirmTitle || '删除照片',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return false
  }

  deletingPhotos.value = true
  try {
    const res = await axios.post('/api/delete/batch', { photo_ids: photoIds })
    const { deleted_count: deletedCount, failed_count: failedCount, failed, deleted } =
      res.data
    if (failedCount > 0) {
      const detailText = (failed || [])
        .map((item) => `${item.photo_id}: ${item.error}`)
        .join('\n')
      ElMessage.warning(`已删除 ${deletedCount} 张，失败 ${failedCount} 张\n${detailText}`)
    } else {
      ElMessage.success(`已删除 ${deletedCount} 张`)
    }
    if (deletedCount > 0) {
      const removed = new Set((deleted || []).map((item) => item.photo_id).filter(Boolean))
      if (detail.value?.photos?.length) {
        detail.value = {
          ...detail.value,
          photos: detail.value.photos.filter((p) => !removed.has(p.photo_id)),
          photo_count: Math.max(0, (detail.value.photo_count || 0) - removed.size),
        }
      }
      selectedPhotoIds.value = selectedPhotoIds.value.filter((id) => !removed.has(id))
      await reloadList()
      await promptRebuildAfterPhotoDelete()
    }
    return deletedCount > 0
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
    return false
  } finally {
    deletingPhotos.value = false
  }
}

async function sendToPaperCut() {
  const ids = [...selectedPhotoIds.value]
  if (!ids.length) {
    ElMessage.warning('请先选择照片')
    return
  }
  sendingPrint.value = true
  try {
    const res = await axios.post('/api/print-outbox', {
      photo_ids: ids,
      open_browser: false,
    })
    const { copied_count: n, failed_count: failedCount, studio_url: url, failed } = res.data
    if (failedCount > 0) {
      const detailText = (failed || []).map((f) => `${f.photo_id}: ${f.error}`).join('\n')
      ElMessage.warning(`已送出 ${n} 张，失败 ${failedCount} 张\n${detailText}`)
    } else {
      ElMessage.success(`已送出 ${n} 张到剪纸排版`)
    }
    if (url) window.open(url, '_blank')
  } catch (err) {
    ElMessage.error(
      err.response?.data?.detail || '送到剪纸失败（请确认剪纸台已启动，且 PAPER_CUT_ROOT 正确）',
    )
  } finally {
    sendingPrint.value = false
  }
}

async function sendToStoryCircle() {
  const ids = [...selectedPhotoIds.value]
  if (!ids.length) {
    ElMessage.warning('请先选择照片')
    return
  }
  const slots = ['骑车', '玩水', '包饺子', '图书馆', '看画展', '看非遗变脸']
  if (ids.length !== slots.length) {
    ElMessage.warning(
      `请按顺序正好勾选 ${slots.length} 张图：${slots.join(' → ')}（当前 ${ids.length} 张）`,
    )
    return
  }
  try {
    await ElMessageBox.confirm(
      `将按勾选顺序套标题：\n${slots.map((t, i) => `${i + 1}. ${t}`).join('\n')}\n\n合照/同学都可以。继续生成？`,
      '自己填图 · 暑假六格',
      { confirmButtonText: '生成分享页', cancelButtonText: '再选选' },
    )
  } catch {
    return
  }
  sendingStory.value = true
  try {
    const res = await axios.post('/api/story-circle/from-photos', {
      photo_ids: ids,
      layout: 'snake',
      use_summer_slots: true,
      title: '面面的开心暑假',
      subtitle: '和同学一起交的暑假快乐事 · 顺着箭头讲',
    })
    const path = res.data?.path
    if (!path) {
      ElMessage.error('未返回分享页地址')
      return
    }
    ElMessage.success(`已用你选的 ${res.data.count} 张排好`)
    window.open(path, '_blank')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '生成分享页失败')
  } finally {
    sendingStory.value = false
  }
}

async function deleteSelectedPhotos() {
  const ids = [...selectedPhotoIds.value]
  if (!ids.length) {
    ElMessage.warning('请先选择照片')
    return
  }
  await deletePhotosByIds(ids, {
    confirmTitle: '批量删除',
    confirmMsg: `确定删除选中的 ${ids.length} 张照片？\n\n原图 + memory JSON 会移入 data/.trash/\nSQLite 索引同步清除（无需再 sync）`,
  })
}

async function deleteOnePhoto(photoId) {
  if (!photoId) return
  await deletePhotosByIds([photoId], {
    confirmTitle: '删除照片',
    confirmMsg: `确定删除这张照片？\n\n${photoId}\n\n原图 + memory JSON 会移入 data/.trash/`,
  })
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
    await loadMemoryLocations()
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
  const params = {
    include_home: includeHome.value,
    time_scope: timeScope.value || 'all',
    location: locationFilter.value.trim() || undefined,
    person: personFilter.value.trim() || undefined,
    keyword: keywordFilter.value.trim() || undefined,
    limit: pageSize,
    offset,
  }
  if (timeScope.value !== 'untimed') {
    const day = dayQuery()
    if (day) params.day = day
  }
  return params
}

function dayLabel(day) {
  return day && String(day).trim() ? day : '无时间'
}

function onTimeScopeChange() {
  if (timeScope.value === 'untimed') {
    yearFilter.value = ''
    monthFilter.value = ''
    dayFilter.value = ''
    // 无时间地点里家照片很多，默认含家以免漏掉
    includeHome.value = true
  }
  onFilterChange()
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
    storyLinkSummaries.value = {}
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
    const untimed = res.data.untimed_location_events || 0
    ElMessage.success(
      `已重建：outing ${res.data.outing_events} / 家 ${res.data.home_events}` +
        (untimed ? ` / 无时间地点 ${untimed}` : ''),
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
  storyLinkSummaries.value = {}
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
    await loadStoryLinkSummaries()
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
  storyLinkSummaries.value = {
    [detail.value.event_id]: {
      day: detail.value.day,
      display_title: detail.value.display_title,
      photo_count: detail.value.photo_count,
      location: detail.value.location,
      is_home: detail.value.is_home,
    },
  }
}

function formatApiError(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const text = detail.map((item) => item?.msg || JSON.stringify(item)).join('；')
    if (text) return text
  }
  if (!err?.response) return `${fallback}（请确认 Desk API 已启动）`
  return fallback
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
    ElMessage.error(formatApiError(err, '保存故事失败'))
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
    storyLinkSummaries.value = {}
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

.time-scope-select {
  width: 120px;
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

.weather-empty {
  color: var(--el-text-color-placeholder);
}

.weather-line {
  color: var(--accent);
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
  background: var(--thumb-bg);
}

.photo-card.selected {
  border-color: rgba(91, 159, 212, 0.95);
  box-shadow: 0 0 0 1px rgba(91, 159, 212, 0.55);
}

.photo-thumb {
  position: relative;
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

.media-badge {
  position: absolute;
  left: 0.3rem;
  bottom: 0.3rem;
  z-index: 2;
  padding: 0.08rem 0.3rem;
  border-radius: 4px;
  font-size: 0.65rem;
  line-height: 1.2;
  color: #fff;
  background: rgba(0, 0, 0, 0.7);
  pointer-events: none;
}

.media-badge.audio {
  background: rgba(30, 80, 120, 0.85);
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

.photo-card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.25rem;
  padding: 0 0.2rem 0.25rem;
}

.photo-detail-link,
.photo-delete-link {
  padding: 0.15rem 0.1rem;
  border: none;
  background: transparent;
  font-size: 0.68rem;
  cursor: pointer;
}

.photo-detail-link {
  color: var(--accent);
}

.photo-delete-link {
  color: #e88a8a;
}

.photo-detail-link:hover,
.photo-delete-link:hover:not(:disabled) {
  text-decoration: underline;
}

.photo-delete-link:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.links-box {
  margin-top: 1rem;
  padding-top: 0.85rem;
  border-top: 1px solid var(--border);
}

.links-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}

.links-box h4 {
  margin: 0;
  font-size: 0.9rem;
}

.section-hint {
  margin: 0 0 0.55rem;
  font-size: 0.75rem;
  line-height: 1.45;
  color: var(--muted);
}

.story-editor .overlay-actions {
  margin-top: 0.65rem;
  margin-bottom: 0.25rem;
}

.link-cards {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.link-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel);
}

.link-card-main {
  min-width: 0;
  flex: 1;
}

.link-card-title {
  font-size: 0.84rem;
  font-weight: 500;
  line-height: 1.35;
}

.link-card-meta {
  margin-top: 0.15rem;
  font-size: 0.72rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.link-card-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.15rem;
}

.link-picker-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.75rem;
}

.dialog-footer-hint {
  margin-top: 0.55rem;
  font-size: 0.75rem;
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
