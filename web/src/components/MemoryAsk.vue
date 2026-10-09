<template>
  <div class="ask-container">
    <aside class="ask-left">
      <p class="hint">
        验证意图与索引：左侧提问，右侧看证据。点图进详情。长期用「错题本」打勾。
      </p>

      <div class="checklist-bar">
        <div class="checklist-stats">
          <span>未测 {{ checklistStats.untested }}</span>
          <span class="ok">好了 {{ checklistStats.pass }}</span>
          <span class="bad">没好 {{ checklistStats.fail }}</span>
        </div>
        <el-button type="primary" plain size="small" @click="openChecklist">
          错题本
        </el-button>
      </div>

      <div class="chips">
        <el-tag
          v-for="chip in exampleChips"
          :key="chip"
          class="chip"
          effect="plain"
          @click="useChip(chip)"
        >
          {{ chip }}
        </el-tag>
      </div>

      <el-input
        v-model="question"
        type="textarea"
        :rows="4"
        placeholder="例如：面面最近去哪了"
        class="question-input"
        @keydown.enter.exact.prevent="submitAsk"
      />

      <el-button
        type="primary"
        class="ask-btn"
        :loading="loading"
        @click="submitAsk"
      >
        提问
      </el-button>

      <div v-if="error" class="ask-error">{{ error }}</div>

      <section v-else-if="result" class="answer-block" v-loading="loading">
        <div class="answer-meta">
          <el-tag size="small" type="info">{{ result.intent || 'unknown' }}</el-tag>
          <el-tag size="small" :type="result.used_llm ? 'success' : 'info'">
            {{ result.used_llm ? 'LLM 润色' : '模板回答' }}
          </el-tag>
        </div>
        <div class="answer-text">{{ result.answer }}</div>

        <div v-if="followUpChips.length" class="follow-ups">
          <span class="follow-label">继续问</span>
          <el-tag
            v-for="chip in followUpChips"
            :key="chip"
            class="chip follow-chip"
            effect="plain"
            type="success"
            @click="askFollowUp(chip)"
          >
            {{ chip }}
          </el-tag>
        </div>

        <div v-if="matchedChecklistItem" class="mark-row">
          <span class="mark-label">本题打勾</span>
          <el-button
            size="small"
            :type="matchedChecklistItem.status === 'pass' ? 'success' : 'default'"
            :loading="marking"
            @click="setItemStatus(matchedChecklistItem, 'pass')"
          >
            好了
          </el-button>
          <el-button
            size="small"
            :type="matchedChecklistItem.status === 'fail' ? 'danger' : 'default'"
            :loading="marking"
            @click="markFailPrompt(matchedChecklistItem)"
          >
            没好
          </el-button>
          <el-button
            size="small"
            text
            :loading="marking"
            @click="setItemStatus(matchedChecklistItem, 'untested')"
          >
            重置
          </el-button>
        </div>
        <el-input
          v-if="matchedChecklistItem && matchedChecklistItem.status === 'fail'"
          v-model="matchedNoteDraft"
          type="textarea"
          :rows="2"
          placeholder="没好时写：期望什么 / 实际答了啥"
          class="mark-note"
          @blur="saveMatchedNote"
        />
      </section>
    </aside>

    <main class="ask-right" v-loading="loading">
      <template v-if="result">
        <div v-if="!hasEvidence" class="ask-empty ask-empty-inline">
          <el-empty description="本次无结构化证据，可看左侧短答或展开下方 facts" />
        </div>

        <section v-if="evidencePhotos.length" class="evidence-block">
          <h3 class="block-title">
            媒体证据 · {{ evidenceTotal }}
            <span v-if="evidenceMediaTypeHint" class="block-sub">
              （{{ evidenceMediaTypeHint }}）
            </span>
            <span v-if="evidenceTotal > evidencePageSize" class="block-sub">
              （每页 {{ evidencePageSize }} 条）
            </span>
          </h3>
          <div class="photo-grid">
            <button
              v-for="photo in pagedEvidencePhotos"
              :key="photo.photo_id"
              type="button"
              class="photo-card"
              @click="emit('view-detail', photo.photo_id)"
            >
              <img
                v-if="photo.source_path"
                :src="previewUrl(photo.source_path)"
                :alt="photo.photo_id"
                loading="lazy"
              />
              <div v-else class="photo-placeholder">无预览</div>
              <div class="photo-meta">
                <div class="photo-line">{{ formatTime(photo.timestamp) }}</div>
                <div class="photo-line muted">
                  <template v-if="photo.media_type && photo.media_type !== 'photo'">
                    [{{ mediaTypeLabel(photo.media_type) }}]
                  </template>
                  {{ photo.location || photo.scene || photo.photo_id }}
                </div>
              </div>
            </button>
          </div>
          <div v-if="evidenceTotal > evidencePageSize" class="evidence-pager">
            <el-pagination
              v-model:current-page="evidencePage"
              :page-size="evidencePageSize"
              :total="evidenceTotal"
              layout="total, prev, pager, next"
              background
              small
            />
          </div>
        </section>

        <section v-if="companions.length" class="evidence-block">
          <h3 class="block-title">同框人物 · {{ companions.length }}</h3>
          <el-table :data="companions" stripe size="small">
            <el-table-column prop="name" label="人物" min-width="120" />
            <el-table-column prop="photo_count" label="同框张数" width="100" align="right" />
          </el-table>
        </section>

        <section v-if="rankPlaces.length" class="evidence-block">
          <h3 class="block-title">地点排行 · {{ rankPlaces.length }}</h3>
          <el-table :data="rankPlaces" stripe size="small">
            <el-table-column
              :prop="rankPlaceLabelKey"
              label="地点"
              min-width="160"
              show-overflow-tooltip
            />
            <el-table-column prop="photo_count" label="张数" width="80" align="right" />
            <el-table-column prop="day_count" label="天数" width="80" align="right" />
          </el-table>
        </section>

        <section v-if="recentPlaces.length" class="evidence-block">
          <h3 class="block-title">最近地点 · {{ recentPlaces.length }}</h3>
          <el-table :data="recentPlaces" stripe size="small">
            <el-table-column prop="timestamp" label="时间" width="170">
              <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
            </el-table-column>
            <el-table-column prop="location" label="地点" min-width="160" show-overflow-tooltip />
            <el-table-column label="样例" width="88" align="center">
              <template #default="{ row }">
                <el-button
                  v-if="row.photo_id"
                  link
                  type="primary"
                  @click="emit('view-detail', row.photo_id)"
                >
                  详情
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-if="visitDays.length" class="evidence-block">
          <h3 class="block-title">到访日期 · {{ visitDays.length }}</h3>
          <el-table :data="visitDays" stripe size="small">
            <el-table-column prop="day" label="日期" width="120" />
            <el-table-column prop="location" label="地点" min-width="140" show-overflow-tooltip />
            <el-table-column prop="photo_count" label="张数" width="80" align="right" />
            <el-table-column prop="age_label" label="年龄" width="100" />
          </el-table>
        </section>

        <section v-if="peakDays.length" class="evidence-block">
          <h3 class="block-title">峰值日 · {{ peakDays.length }}</h3>
          <el-table :data="peakDays" stripe size="small">
            <el-table-column prop="day" label="日期" width="120" />
            <el-table-column prop="photo_count" label="张数" width="80" align="right" />
            <el-table-column
              prop="primary_location"
              label="主要地点"
              min-width="160"
              show-overflow-tooltip
            />
            <el-table-column prop="age_label" label="年龄" width="100" />
          </el-table>
        </section>

        <section v-if="statsRows.length" class="evidence-block">
          <h3 class="block-title">统计</h3>
          <el-table :data="statsRows" stripe size="small">
            <el-table-column prop="label" label="项" min-width="140" />
            <el-table-column prop="value" label="值" min-width="120" />
          </el-table>
        </section>

        <section v-if="homeTimeline.length" class="evidence-block">
          <h3 class="block-title">住过哪 · {{ homeTimeline.length }}</h3>
          <el-table :data="homeTimeline" stripe size="small">
            <el-table-column prop="location" label="住址" min-width="140" show-overflow-tooltip />
            <el-table-column label="时段" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.first_day }}～{{ row.last_day }}
              </template>
            </el-table-column>
            <el-table-column prop="span_days" label="天数" width="72" align="right" />
            <el-table-column label="年龄" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                <template v-if="row.age_start_label && row.age_end_label">
                  {{ row.age_start_label }}～{{ row.age_end_label }}
                </template>
                <template v-else>{{ row.age_start_label || '—' }}</template>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-if="outingEvents.length" class="evidence-block">
          <h3 class="block-title">
            出门事件 · {{ outingEvents.length }}
            <span class="block-sub">（点击一行查看照片）</span>
          </h3>
          <el-table
            :data="outingEvents"
            stripe
            size="small"
            highlight-current-row
            :row-class-name="outingRowClass"
            class="outing-table"
            @row-click="selectOutingEvent"
          >
            <el-table-column prop="day" label="日期" width="120" />
            <el-table-column prop="display_title" label="标题" min-width="180" show-overflow-tooltip />
            <el-table-column prop="photo_count" label="张数" width="80" align="right" />
            <el-table-column label="人物" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">
                {{ (row.people || []).join('、') }}
              </template>
            </el-table-column>
          </el-table>

          <div v-if="selectedOutingId" class="outing-photos" v-loading="outingPhotosLoading">
            <h4 class="outing-photos-title">
              {{ selectedOutingTitle }}
              <span class="block-sub">· {{ outingPhotos.length }} 张</span>
            </h4>
            <div v-if="outingPhotosError" class="ask-error">{{ outingPhotosError }}</div>
            <div v-else-if="!outingPhotosLoading && !outingPhotos.length" class="ask-empty-inline">
              <el-empty description="该事件没有关联照片" :image-size="64" />
            </div>
            <div v-else class="photo-grid">
              <button
                v-for="photo in outingPhotos"
                :key="photo.photo_id"
                type="button"
                class="photo-card"
                @click="emit('view-detail', photo.photo_id)"
              >
                <img
                  v-if="photo.source_path"
                  :src="previewUrl(photo.source_path)"
                  :alt="photo.photo_id"
                  loading="lazy"
                />
                <div v-else class="photo-placeholder">无预览</div>
                <div class="photo-meta">
                  <div class="photo-line">{{ formatTime(photo.timestamp) }}</div>
                  <div class="photo-line muted">
                    {{ photo.location || photo.scene || photo.photo_id }}
                  </div>
                </div>
              </button>
            </div>
          </div>
        </section>

        <section v-if="storyItems.length" class="evidence-block">
          <h3 class="block-title">故事 · {{ storyItems.length }}</h3>
          <div v-for="s in storyItems" :key="s.story_id" class="story-card">
            <div class="story-title">{{ s.title || '未命名' }}</div>
            <pre class="story-body">{{ s.body || '（无正文）' }}</pre>
          </div>
        </section>

        <section class="evidence-block facts-block">
          <el-collapse>
            <el-collapse-item title="原始 facts（调试）" name="facts">
              <pre class="facts-json">{{ factsJson }}</pre>
            </el-collapse-item>
          </el-collapse>
        </section>
      </template>

      <div v-else class="ask-empty">
        <el-empty description="选左侧示例，或打开错题本逐条测" />
      </div>
    </main>

    <el-drawer
      v-model="checklistOpen"
      title="问答错题本"
      size="440px"
      direction="rtl"
    >
      <p class="drawer-hint">
        点问句即提问；答完后在左侧标「好了 / 没好」。状态保存在 Mac
        <code>data/ask_checklist.json</code>。
      </p>

      <div class="drawer-filters">
        <el-radio-group v-model="checklistFilter" size="small">
          <el-radio-button label="all">全部</el-radio-button>
          <el-radio-button label="untested">未测</el-radio-button>
          <el-radio-button label="fail">没好</el-radio-button>
          <el-radio-button label="pass">好了</el-radio-button>
        </el-radio-group>
      </div>

      <div class="add-row">
        <el-input
          v-model="newQuestion"
          size="small"
          placeholder="加一条自家问句"
          @keydown.enter.exact.prevent="addChecklistItem"
        />
        <el-button size="small" type="primary" :loading="adding" @click="addChecklistItem">
          添加
        </el-button>
      </div>

      <div v-loading="checklistLoading" class="checklist-list">
        <div
          v-for="group in groupedChecklist"
          :key="group.section"
          class="checklist-section"
        >
          <h4 class="section-title">{{ group.section }}</h4>
          <button
            v-for="item in group.items"
            :key="item.id"
            type="button"
            class="checklist-item"
            :class="`st-${item.status}`"
            @click="askFromChecklist(item)"
          >
            <span class="item-status">{{ statusLabel(item.status) }}</span>
            <span class="item-q">{{ item.question }}</span>
            <span v-if="item.intent_hint" class="item-hint">{{ item.intent_hint }}</span>
            <span v-if="item.note" class="item-note">{{ item.note }}</span>
          </button>
        </div>
        <el-empty
          v-if="!groupedChecklist.length"
          description="该筛选下没有条目"
          :image-size="72"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const emit = defineEmits(['view-detail'])

const exampleChips = [
  '面面最近去哪了',
  '最近出去玩了哪些',
  '去年国庆去哪里玩了',
  '去年国庆去哪里玩了？开心吗？见了哪些人？',
  '面面2024年出去玩了哪些',
  '去年春天出门',
  '面面住过哪些地方',
  '面面在哪个地方呆的时间最长',
  '面面骑车',
  '有没有轮滑',
  '面面的画作',
  '面面去动物园是什么时候',
  '面面哪些人去过动物园',
  '妈妈和面面的合影',
  '面面和哪个人的合影最多',
  '面面和笑笑合影',
  '面面哭',
  '面面几岁了',
  '面面最近10张照片',
  '一共多少张照片',
  '轮滑故事',
]

const question = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null)
/** 上一轮 turn_context，供追问带上 */
const askContext = ref(null)
const evidencePage = ref(1)
const evidencePageSize = 20
const selectedOutingId = ref('')
const selectedOutingTitle = ref('')
const outingPhotos = ref([])
const outingPhotosLoading = ref(false)
const outingPhotosError = ref('')

const checklistOpen = ref(false)
const checklistLoading = ref(false)
const checklistItems = ref([])
const checklistStats = ref({ total: 0, untested: 0, pass: 0, fail: 0 })
const checklistFilter = ref('all')
const newQuestion = ref('')
const adding = ref(false)
const marking = ref(false)
const matchedNoteDraft = ref('')
const activeChecklistId = ref('')

const facts = computed(() => result.value?.facts || {})

const followUpChips = computed(() => {
  const list = result.value?.follow_ups
  return Array.isArray(list) ? list.filter((x) => typeof x === 'string' && x.trim()) : []
})

const matchedChecklistItem = computed(() => {
  const q = question.value.trim()
  if (!q) return null
  if (activeChecklistId.value) {
    const byId = checklistItems.value.find((x) => x.id === activeChecklistId.value)
    if (byId) return byId
  }
  return checklistItems.value.find((x) => x.question === q) || null
})

const groupedChecklist = computed(() => {
  const filter = checklistFilter.value
  const rows = checklistItems.value.filter((item) => {
    if (filter === 'all') return true
    return item.status === filter
  })
  const map = new Map()
  for (const item of rows) {
    const key = item.section || '其它'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(item)
  }
  return [...map.entries()].map(([section, items]) => ({ section, items }))
})

watch(matchedChecklistItem, (item) => {
  matchedNoteDraft.value = item?.note || ''
})

onMounted(() => {
  loadChecklist()
})

const factsJson = computed(() => {
  try {
    return JSON.stringify(facts.value, null, 2)
  } catch {
    return String(facts.value)
  }
})

/** 排行类 places：有 photo_count，无单张 photo_id */
const rankPlaces = computed(() => {
  const places = facts.value.places
  if (!Array.isArray(places) || !places.length) return []
  const first = places[0]
  if (!first || typeof first !== 'object') return []
  if ('photo_count' in first || 'day_count' in first || 'label' in first) {
    return places
  }
  return []
})

const rankPlaceLabelKey = computed(() => {
  const row = rankPlaces.value[0]
  if (row?.location != null) return 'location'
  if (row?.label != null) return 'label'
  return 'location'
})

/** 最近地点：带 timestamp + location，常有 photo_id */
const recentPlaces = computed(() => {
  const places = facts.value.places
  if (!Array.isArray(places) || !places.length) return []
  const first = places[0]
  if (!first || typeof first !== 'object') return []
  if ('timestamp' in first && 'location' in first && !('photo_count' in first)) {
    return places
  }
  return []
})

const visitDays = computed(() => {
  const days = facts.value.visit_days
  return Array.isArray(days) ? days : []
})

const companions = computed(() => {
  const list = facts.value.companions
  return Array.isArray(list) ? list : []
})

const peakDays = computed(() => {
  const days = facts.value.peak_days
  return Array.isArray(days) ? days : []
})

const evidencePhotos = computed(() => {
  // 优先统一 evidence 合同；否则回退拼 facts
  const evMedia = result.value?.evidence?.media
  if (Array.isArray(evMedia) && evMedia.length) {
    return evMedia.map((m) => ({
      photo_id: m.id || m.photo_id || '',
      media_type: m.media_type || 'photo',
      timestamp: m.timestamp || '',
      location: m.location || '',
      scene: m.scene || '',
      source_path: m.source_path || '',
    }))
  }
  const seen = new Set()
  const out = []

  const push = (p) => {
    if (!p || typeof p !== 'object') return
    const id = String(p.photo_id || '').trim()
    if (!id || seen.has(id)) return
    seen.add(id)
    out.push(p)
  }

  for (const key of ['photos', 'sample_photos']) {
    const list = facts.value[key]
    if (Array.isArray(list)) list.forEach(push)
  }
  for (const key of ['photo', 'first_visit', 'last_visit']) {
    push(facts.value[key])
  }
  for (const p of recentPlaces.value) {
    push(p)
  }
  return out
})

const evidenceMediaTypeHint = computed(() => {
  const by = result.value?.evidence?.counts?.by_media_type
  if (!by || typeof by !== 'object') return ''
  const parts = []
  if (by.photo) parts.push(`照片 ${by.photo}`)
  if (by.video) parts.push(`视频 ${by.video}`)
  if (by.audio) parts.push(`音频 ${by.audio}`)
  return parts.join(' · ')
})

function mediaTypeLabel(mt) {
  if (mt === 'video') return '视频'
  if (mt === 'audio') return '音频'
  return '照片'
}

const evidenceTotal = computed(() => {
  const n = evidencePhotos.value.length
  const counted = Number(facts.value.photo_count ?? facts.value.total_count)
  if (!Number.isFinite(counted) || counted <= 0) return n
  // 声称总数远大于实际返回的缩略图 → 按实际列表分页，避免空页
  if (n > 0 && counted > n + 2) return n
  return Math.max(counted, n)
})

const pagedEvidencePhotos = computed(() => {
  const start = (evidencePage.value - 1) * evidencePageSize
  return evidencePhotos.value.slice(start, start + evidencePageSize)
})

const statsRows = computed(() => {
  const stats = facts.value.stats
  if (!stats || typeof stats !== 'object') return []
  const rows = []
  const walk = (obj, prefix = '') => {
    for (const [k, v] of Object.entries(obj)) {
      const label = prefix ? `${prefix}.${k}` : k
      if (v != null && typeof v === 'object' && !Array.isArray(v)) {
        walk(v, label)
      } else if (!Array.isArray(v)) {
        rows.push({ label, value: String(v) })
      }
    }
  }
  walk(stats)
  return rows
})

const outingEvents = computed(() => {
  const events = facts.value.events
  return Array.isArray(events) ? events : []
})

const homeTimeline = computed(() => {
  const homes = facts.value.homes
  return Array.isArray(homes) ? homes : []
})

const storyItems = computed(() => {
  const stories = facts.value.stories
  return Array.isArray(stories) ? stories : []
})

const hasEvidence = computed(
  () =>
    evidencePhotos.value.length > 0 ||
    rankPlaces.value.length > 0 ||
    recentPlaces.value.length > 0 ||
    companions.value.length > 0 ||
    visitDays.value.length > 0 ||
    peakDays.value.length > 0 ||
    statsRows.value.length > 0 ||
    outingEvents.value.length > 0 ||
    homeTimeline.value.length > 0 ||
    storyItems.value.length > 0,
)

function statusLabel(status) {
  if (status === 'pass') return '好了'
  if (status === 'fail') return '没好'
  return '未测'
}

function applyStats(stats) {
  if (!stats || typeof stats !== 'object') return
  checklistStats.value = {
    total: stats.total || 0,
    untested: stats.untested || 0,
    pass: stats.pass || 0,
    fail: stats.fail || 0,
  }
}

async function loadChecklist() {
  checklistLoading.value = true
  try {
    const res = await axios.get('/api/ask/checklist')
    checklistItems.value = Array.isArray(res.data?.items) ? res.data.items : []
    applyStats(res.data?.stats)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || '加载错题本失败')
  } finally {
    checklistLoading.value = false
  }
}

function openChecklist() {
  checklistOpen.value = true
  loadChecklist()
}

function askFromChecklist(item) {
  activeChecklistId.value = item.id
  question.value = item.question
  checklistOpen.value = false
  submitAsk()
}

function askFollowUp(chip) {
  const text = String(chip || '').trim()
  if (!text) return
  question.value = text
  submitAsk({ withContext: true })
}

async function setItemStatus(item, status, note) {
  if (!item?.id) return
  marking.value = true
  try {
    const body = { status }
    if (note !== undefined) body.note = note
    const res = await axios.patch(`/api/ask/checklist/${encodeURIComponent(item.id)}`, body)
    const updated = res.data?.item
    if (updated) {
      const idx = checklistItems.value.findIndex((x) => x.id === updated.id)
      if (idx >= 0) checklistItems.value[idx] = updated
      else checklistItems.value.push(updated)
    }
    applyStats(res.data?.stats)
    if (status === 'pass') ElMessage.success('已标好了')
    else if (status === 'fail') ElMessage.warning('已标没好')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || '更新失败')
  } finally {
    marking.value = false
  }
}

async function markFailPrompt(item) {
  try {
    const { value } = await ElMessageBox.prompt(
      '期望什么 / 实际答了啥（可留空）',
      '标为没好',
      {
        confirmButtonText: '没好',
        cancelButtonText: '取消',
        inputValue: item.note || '',
        inputPlaceholder: '可选备注',
      },
    )
    matchedNoteDraft.value = value || ''
    await setItemStatus(item, 'fail', value || '')
  } catch {
    /* cancel */
  }
}

async function saveMatchedNote() {
  const item = matchedChecklistItem.value
  if (!item) return
  const note = matchedNoteDraft.value
  if ((item.note || '') === note) return
  marking.value = true
  try {
    const res = await axios.patch(`/api/ask/checklist/${encodeURIComponent(item.id)}`, {
      note,
    })
    const updated = res.data?.item
    if (updated) {
      const idx = checklistItems.value.findIndex((x) => x.id === updated.id)
      if (idx >= 0) checklistItems.value[idx] = updated
    }
    applyStats(res.data?.stats)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || '保存备注失败')
  } finally {
    marking.value = false
  }
}

async function addChecklistItem() {
  const q = newQuestion.value.trim()
  if (!q) {
    ElMessage.warning('请输入问句')
    return
  }
  adding.value = true
  try {
    const res = await axios.post('/api/ask/checklist', {
      question: q,
      section: '自家补充',
    })
    if (res.data?.item) checklistItems.value.push(res.data.item)
    applyStats(res.data?.stats)
    newQuestion.value = ''
    ElMessage.success('已添加')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || '添加失败')
  } finally {
    adding.value = false
  }
}

function useChip(text) {
  activeChecklistId.value = ''
  question.value = text
  submitAsk()
}

function clearOutingSelection() {
  selectedOutingId.value = ''
  selectedOutingTitle.value = ''
  outingPhotos.value = []
  outingPhotosError.value = ''
  outingPhotosLoading.value = false
}

function outingRowClass({ row }) {
  return row?.event_id && row.event_id === selectedOutingId.value ? 'is-selected-outing' : ''
}

async function selectOutingEvent(row) {
  const eventId = String(row?.event_id || '').trim()
  if (!eventId) {
    ElMessage.warning('该事件缺少 event_id，无法加载照片')
    return
  }
  // 再点同一行 → 收起
  if (selectedOutingId.value === eventId) {
    clearOutingSelection()
    return
  }
  selectedOutingId.value = eventId
  selectedOutingTitle.value =
    row.display_title || `${row.day || ''} · ${row.location || '未知地点'}`
  outingPhotos.value = []
  outingPhotosError.value = ''
  outingPhotosLoading.value = true
  try {
    const res = await axios.get(`/api/events/${encodeURIComponent(eventId)}`)
    outingPhotos.value = Array.isArray(res.data?.photos) ? res.data.photos : []
  } catch (err) {
    outingPhotosError.value =
      err.response?.data?.detail || err.message || '加载事件照片失败'
  } finally {
    outingPhotosLoading.value = false
  }
}

async function submitAsk(opts = {}) {
  const q = question.value.trim()
  if (!q) {
    ElMessage.warning('请输入问题')
    return
  }
  if (
    activeChecklistId.value &&
    !checklistItems.value.some(
      (x) => x.id === activeChecklistId.value && x.question === q,
    )
  ) {
    activeChecklistId.value = ''
  }
  loading.value = true
  error.value = ''
  evidencePage.value = 1
  clearOutingSelection()
  try {
    const payload = { question: q }
    if (opts.withContext && askContext.value) {
      payload.context = askContext.value
    }
    const res = await axios.post('/api/ask', payload)
    result.value = res.data
    askContext.value = res.data?.context || null
  } catch (err) {
    result.value = null
    error.value =
      err.response?.data?.detail ||
      err.message ||
      '问答失败，请确认 Desk 已启动'
  } finally {
    loading.value = false
  }
}

function previewUrl(path) {
  return `/api/preview?path=${encodeURIComponent(path)}&size=640`
}

function formatTime(timestamp) {
  if (!timestamp) return '—'
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp
  const y = date.getFullYear()
  const m = date.getMonth() + 1
  const d = date.getDate()
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${y}/${m}/${d} ${hh}:${mm}`
}
</script>

<style scoped>
.ask-container {
  height: 100%;
  min-height: 0;
  display: flex;
  gap: 1rem;
  overflow: hidden;
}

.ask-left {
  flex: 0 0 360px;
  width: 360px;
  min-width: 300px;
  max-width: 40%;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 0;
  overflow: auto;
  padding-right: 0.25rem;
  border-right: 1px solid var(--border);
  padding-right: 1rem;
}

.ask-right {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  padding-left: 0.25rem;
}

.hint {
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
  line-height: 1.4;
}

.checklist-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.checklist-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  font-size: 0.8rem;
  color: var(--muted);
}

.checklist-stats .ok {
  color: #67c23a;
}

.checklist-stats .bad {
  color: #f56c6c;
}

.mark-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.75rem;
  padding-top: 0.65rem;
  border-top: 1px solid var(--border);
}

.mark-label {
  font-size: 0.8rem;
  color: var(--muted);
  margin-right: 0.15rem;
}

.mark-note {
  margin-top: 0.5rem;
}

.drawer-hint {
  margin: 0 0 0.85rem;
  font-size: 0.82rem;
  color: var(--muted);
  line-height: 1.45;
}

.drawer-hint code {
  font-size: 0.78rem;
}

.drawer-filters {
  margin-bottom: 0.75rem;
}

.add-row {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 1rem;
}

.checklist-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 120px;
}

.checklist-section {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.section-title {
  margin: 0 0 0.2rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--muted);
}

.checklist-item {
  display: grid;
  grid-template-columns: 2.6rem 1fr;
  grid-template-rows: auto auto;
  gap: 0.1rem 0.55rem;
  text-align: left;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-2);
  cursor: pointer;
  color: inherit;
  font: inherit;
}

.checklist-item:hover {
  border-color: var(--accent);
}

.checklist-item.st-pass {
  border-color: #b3e19d;
}

.checklist-item.st-fail {
  border-color: #fbc4c4;
}

.item-status {
  grid-row: 1 / span 2;
  align-self: center;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--muted);
}

.st-pass .item-status {
  color: #67c23a;
}

.st-fail .item-status {
  color: #f56c6c;
}

.item-q {
  font-size: 0.88rem;
  line-height: 1.35;
}

.item-hint {
  grid-column: 2;
  font-size: 0.72rem;
  color: var(--muted);
}

.item-note {
  grid-column: 2;
  font-size: 0.75rem;
  color: #e6a23c;
  line-height: 1.3;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.chip {
  cursor: pointer;
  max-width: 100%;
  height: auto;
  white-space: normal;
  line-height: 1.35;
  padding: 0.2rem 0.5rem;
}

.chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.question-input {
  flex-shrink: 0;
}

.ask-btn {
  width: 100%;
  flex-shrink: 0;
}

.ask-error {
  color: #f56c6c;
  font-size: 0.9rem;
  line-height: 1.4;
}

.ask-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ask-empty-inline {
  flex: 0 0 auto;
  min-height: 160px;
}

.answer-block {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.85rem 0.95rem;
  flex: 1;
  min-height: 0;
}

.answer-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-bottom: 0.55rem;
}

.answer-text {
  white-space: pre-wrap;
  line-height: 1.55;
  color: var(--text-strong);
  font-size: 0.92rem;
}

.follow-ups {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.65rem;
}

.follow-label {
  font-size: 0.78rem;
  color: var(--muted);
  margin-right: 0.15rem;
}

.follow-chip {
  cursor: pointer;
}

.evidence-block {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.block-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text);
}

.block-sub {
  margin-left: 0.35rem;
  font-size: 0.8rem;
  font-weight: 400;
  color: var(--text-muted, #888);
}

.evidence-pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 0.25rem;
}

.outing-table {
  cursor: pointer;
}

.outing-table :deep(.is-selected-outing) > td {
  background: color-mix(in srgb, var(--accent, #409eff) 12%, transparent) !important;
}

.outing-photos {
  margin-top: 0.35rem;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-2, transparent);
  min-height: 4rem;
}

.outing-photos-title {
  margin: 0 0 0.65rem;
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text);
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.75rem;
}

.photo-card {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-2);
  overflow: hidden;
  cursor: pointer;
  text-align: left;
  color: inherit;
}

.photo-card:hover {
  border-color: var(--accent);
}

.photo-card img,
.photo-placeholder {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  background: var(--thumb-bg);
}

.photo-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 0.8rem;
}

.photo-meta {
  padding: 0.35rem 0.5rem 0.55rem;
}

.photo-line {
  font-size: 0.75rem;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.photo-line.muted {
  color: var(--muted);
}

.facts-json {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  font-size: 0.75rem;
  line-height: 1.4;
  color: var(--muted);
  white-space: pre-wrap;
  word-break: break-word;
}

.story-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem 0.9rem;
  background: var(--panel-2);
  margin-bottom: 0.5rem;
}

.story-title {
  font-weight: 600;
  margin-bottom: 0.4rem;
}

.story-body {
  margin: 0;
  white-space: pre-wrap;
  font-family: inherit;
  font-size: 0.88rem;
  line-height: 1.5;
  color: var(--text);
}

@media (max-width: 900px) {
  .ask-container {
    flex-direction: column;
  }

  .ask-left {
    flex: 0 0 auto;
    width: 100%;
    max-width: none;
    border-right: none;
    border-bottom: 1px solid var(--border);
    padding-right: 0;
    padding-bottom: 1rem;
    max-height: 45%;
  }

  .ask-right {
    padding-left: 0;
  }
}
</style>
