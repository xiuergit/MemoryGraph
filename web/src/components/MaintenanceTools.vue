<template>
  <div class="tools-container">
    <p class="intro">
      改完「地址缓存」或「人脸库」后，在这里一键跑后续步骤，不必记 CLI。
    </p>
    <div v-if="runtimeConfig" class="config-bar">
      <el-tag type="info">识别阈值 {{ runtimeConfig.face_match_threshold }}</el-tag>
      <el-tag v-if="runtimeConfig.index_json_threshold != null" type="warning">
        index.json 快照 {{ runtimeConfig.index_json_threshold }}（仅记录，识别以左为准）
      </el-tag>
      <el-tag :type="runtimeConfig.clip_enabled ? 'success' : 'info'">
        CLIP {{ runtimeConfig.clip_enabled ? '开' : '关' }}
      </el-tag>
    </div>

    <!-- ① 媒体入库 -->
    <el-card class="tool-card section-card" shadow="never">
      <template #header>
        <div class="section-header">
          <span class="card-title">📥 媒体入库</span>
          <el-button size="small" :loading="pendingLoading" @click="refreshPending">
            刷新待入库
          </el-button>
        </div>
      </template>

      <div class="pending-bar">
        <span class="pending-label">{{ mediaScopeLabel }}</span>
        <el-tag type="warning" effect="plain">
          照片待入库 {{ pending.photos.pending }}
          <span class="pending-sub">/ {{ pending.photos.total_files }} 文件</span>
        </el-tag>
        <el-tag type="warning" effect="plain">
          视频待入库 {{ pending.videos.pending }}
          <span class="pending-sub">/ {{ pending.videos.total_files }} 文件</span>
        </el-tag>
      </div>

      <el-card
        v-if="job.running || job.phase === 'done' || job.phase === 'cancelled' || job.error"
        class="job-card inner-card"
        shadow="never"
      >
        <div v-if="job.running" class="job-running">
          <div class="job-title">{{ jobKindLabel(job.kind) }} · {{ jobScopeLabel(job.year) }}</div>
          <el-progress
            :percentage="jobProgressPercent"
            :stroke-width="10"
            :status="job.phase === 'sync' ? 'warning' : undefined"
          />
          <div class="job-stats">{{ jobProgressText }}</div>
          <div v-if="job.current_file" class="job-file">{{ job.current_file }}</div>
          <div class="job-actions">
            <el-button size="small" type="danger" plain :loading="jobCancelling" @click="cancelJob">
              停止本批
            </el-button>
          </div>
          <p class="step-hint job-hint">
            当前这张/这条 AI 跑完后停止；可设「本次上限」分批入库。
          </p>
        </div>
        <div v-else-if="job.error" class="result-box error-box">{{ job.error }}</div>
        <div v-else-if="job.phase === 'cancelled' && job.result?.process" class="result-box">
          已停止 · 本批成功 {{ job.result.process.success }} · 跳过 {{ job.result.process.skipped }} ·
          失败 {{ job.result.process.failed }}
        </div>
        <div v-else-if="job.result?.process" class="result-box">
          完成 · 本批成功 {{ job.result.process.success }} · 跳过 {{ job.result.process.skipped }} ·
          失败 {{ job.result.process.failed }}
          <span v-if="job.result.sync">
            · sync 新增 {{ job.result.sync.added }} · 更新 {{ job.result.sync.updated }}
          </span>
        </div>
      </el-card>

      <el-row :gutter="20" class="media-row">
        <el-col :span="12" :xs="24">
          <div class="media-panel">
            <div class="media-panel-title">📷 照片 JSON</div>
            <p class="step-hint">只处理<strong>尚无 JSON</strong>的新图；已有 JSON 和手改过的跳过。</p>
            <el-form label-width="88px" @submit.prevent>
              <el-form-item label="年份">
                <el-select
                  v-model="photos.year"
                  filterable
                  allow-create
                  default-first-option
                  placeholder="如 2026"
                  class="year-select"
                  @change="onMediaYearChange"
                >
                  <el-option
                    v-for="y in availableYears"
                    :key="y"
                    :label="y"
                    :value="y"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="本次上限">
                <el-input-number
                  v-model="photos.limit"
                  :min="1"
                  :max="50000"
                  controls-position="right"
                  class="limit-input"
                />
                <span class="inline-hint">按成功写入计；留空=该年全部待入库</span>
              </el-form-item>
              <el-form-item label="完成后">
                <el-checkbox v-model="photos.sync_after">同步 SQLite 索引</el-checkbox>
              </el-form-item>
            </el-form>
            <div class="media-actions">
              <el-button
                type="primary"
                :disabled="job.running"
                :loading="loading.processPhotos"
                @click="runProcessPhotos(false)"
              >
                更新照片 JSON
              </el-button>
              <el-button
                v-if="pending.photos.pending > 0 && !job.running"
                plain
                @click="runProcessPhotos(true)"
              >
                继续下一批（剩 {{ pending.photos.pending }}）
              </el-button>
            </div>
            <pre class="cli-hint">python tools/photo2json/main.py --input data/photos/2026 [--limit N]</pre>
            <div v-if="results.photos" class="result-box">
              本批成功 {{ results.photos.process.success }} · 跳过 {{ results.photos.process.skipped }} ·
              失败 {{ results.photos.process.failed }}
              <span v-if="results.photos.sync">
                · sync 新增 {{ results.photos.sync.added }}
              </span>
            </div>
          </div>
        </el-col>

        <el-col :span="12" :xs="24">
          <div class="media-panel">
            <div class="media-panel-title">🎬 视频 JSON</div>
            <p class="step-hint">只处理<strong>尚无 JSON</strong>的新视频；已有 JSON 和手改过的跳过。</p>
            <el-form label-width="88px" @submit.prevent>
              <el-form-item label="年份">
                <el-select
                  v-model="videos.year"
                  filterable
                  allow-create
                  default-first-option
                  placeholder="如 2026"
                  class="year-select"
                  @change="onVideoYearChange"
                >
                  <el-option
                    v-for="y in availableYears"
                    :key="y"
                    :label="y"
                    :value="y"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="月/时段">
                <el-select
                  v-model="videos.month"
                  filterable
                  clearable
                  placeholder="整年（点此选月/时段）"
                  class="month-select"
                  :disabled="!availableMonths.length"
                  @change="onVideoMonthChange"
                >
                  <el-option
                    v-for="m in availableMonths"
                    :key="m"
                    :label="m"
                    :value="m"
                  />
                </el-select>
                <span class="inline-hint">{{ monthSelectHint }}</span>
              </el-form-item>
              <el-form-item label="本次上限">
                <el-input-number
                  v-model="videos.limit"
                  :min="1"
                  :max="50000"
                  controls-position="right"
                  class="limit-input"
                />
                <span class="inline-hint">留空=该范围全部待入库</span>
              </el-form-item>
              <el-form-item label="模式">
                <el-checkbox v-model="videos.no_ai">仅元数据（--no-ai）</el-checkbox>
              </el-form-item>
              <el-form-item label="完成后">
                <el-checkbox v-model="videos.sync_after">同步 SQLite 索引</el-checkbox>
              </el-form-item>
            </el-form>
            <div class="media-actions">
              <el-button
                type="primary"
                :disabled="job.running"
                :loading="loading.processVideos"
                @click="runProcessVideos(false)"
              >
                更新视频 JSON
              </el-button>
              <el-button
                v-if="pending.videos.pending > 0 && !job.running"
                plain
                @click="runProcessVideos(true)"
              >
                继续下一批（剩 {{ pending.videos.pending }}）
              </el-button>
            </div>
            <pre class="cli-hint">python tools/video2json/main.py --input data/photos/{{ videoCliPath }} [--limit N] [--no-ai]</pre>
            <div v-if="results.videos" class="result-box">
              本批成功 {{ results.videos.process.success }} · 跳过 {{ results.videos.process.skipped }} ·
              失败 {{ results.videos.process.failed }}
              <span v-if="results.videos.sync">
                · sync 新增 {{ results.videos.sync.added }}
              </span>
            </div>
          </div>
        </el-col>
      </el-row>

      <div class="media-panel transcript-panel">
        <div class="media-panel-title">字幕 ASR（已有视频 JSON）</div>
        <p class="step-hint">
          与「更新视频 JSON」分开：先有视频 JSON，再按年/月写本地 Whisper 字幕。短于 3 秒默认跳过；覆盖请勾「强制重跑」。
        </p>
        <el-form label-width="88px" @submit.prevent>
          <el-form-item label="年份">
            <el-select
              v-model="transcript.year"
              filterable
              allow-create
              default-first-option
              placeholder="如 2026"
              class="year-select"
              @change="onTranscriptYearChange"
            >
              <el-option
                v-for="y in availableYears"
                :key="`tr-${y}`"
                :label="y"
                :value="y"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="月/时段">
            <el-select
              v-model="transcript.month"
              filterable
              clearable
              placeholder="整年（可选月文件夹）"
              class="month-select"
              :disabled="!transcriptMonths.length"
            >
              <el-option
                v-for="m in transcriptMonths"
                :key="`tr-m-${m}`"
                :label="m"
                :value="m"
              />
            </el-select>
            <span class="inline-hint">清空=整年</span>
          </el-form-item>
          <el-form-item label="本次上限">
            <el-input-number
              v-model="transcript.limit"
              :min="1"
              :max="50000"
              controls-position="right"
              class="limit-input"
            />
            <span class="inline-hint">按成功写入计；长视频很慢，先小批量</span>
          </el-form-item>
          <el-form-item label="选项">
            <el-checkbox v-model="transcript.force">强制重跑（覆盖已有字幕）</el-checkbox>
            <el-checkbox v-model="transcript.sync_after">完成后同步索引</el-checkbox>
          </el-form-item>
        </el-form>
        <div class="media-actions">
          <el-button
            type="primary"
            :disabled="job.running"
            :loading="loading.backfillTranscript"
            @click="runBackfillTranscript"
          >
            写字幕
          </el-button>
        </div>
        <pre class="cli-hint">python tools/video2json/main.py --backfill transcript --year {{ transcript.year || '2026' }} [--limit N] [--force]</pre>
        <div v-if="results.transcript" class="result-box">
          本批更新 {{ results.transcript.process?.success ?? results.transcript.transcript?.updated }} ·
          跳过 {{ results.transcript.process?.skipped ?? results.transcript.transcript?.skipped }} ·
          失败 {{ results.transcript.process?.failed ?? results.transcript.transcript?.failed }}
          <span v-if="results.transcript.sync">
            · sync 新增 {{ results.transcript.sync.added }} · 更新 {{ results.transcript.sync.updated }}
          </span>
        </div>
      </div>
    </el-card>

    <!-- ② 数据修正 -->
    <div class="section-label">数据修正</div>
    <el-row :gutter="20">
      <el-col :span="12" :xs="24">
        <el-card class="tool-card" shadow="never">
          <template #header>
            <span class="card-title">📍 地址（改完地址缓存后）</span>
          </template>
          <p class="step-hint">顺序：地址缓存 Tab 编辑 → 下方「应用缓存到 JSON」→ 完成</p>
          <el-form label-width="100px" @submit.prevent>
            <el-form-item label="本次上限">
              <el-input-number
                v-model="regeocode.limit"
                :min="1"
                :max="50000"
                placeholder="留空=全库"
                controls-position="right"
                class="limit-input"
              />
              <span class="inline-hint">留空处理全库（较慢）</span>
            </el-form-item>
            <el-form-item label="完成后">
              <el-checkbox v-model="regeocode.sync_after">同步 SQLite 索引</el-checkbox>
            </el-form-item>
          </el-form>
          <el-button type="primary" :loading="loading.regeocode" @click="runRegeocode">
            应用缓存到 JSON
          </el-button>
          <pre class="cli-hint">python tools/photo2json/main.py --regeocode-locations --no-normalize-after</pre>
          <div v-if="results.regeocode" class="result-box">
            <div>regeocode: 扫描 {{ results.regeocode.regeocode.total }} · 更新 {{ results.regeocode.regeocode.updated }} · 跳过 {{ results.regeocode.regeocode.skipped }}</div>
            <div v-if="results.regeocode.sync">
              sync: 新增 {{ results.regeocode.sync.added }} · 更新 {{ results.regeocode.sync.updated }}
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12" :xs="24">
        <el-card class="tool-card" shadow="never">
          <template #header>
            <span class="card-title">👤 人脸（入库 / 改参考照后）</span>
          </template>
          <p class="step-hint">Vue 详情入库已自动 build index；手动改 faces/ 目录后点「重建 index」</p>
          <el-button :loading="loading.rebuildIndex" @click="runRebuildIndex">
            重建人脸 index
          </el-button>
          <pre class="cli-hint">python tools/face_enroll/main.py build</pre>
          <el-divider />
          <el-form label-width="100px" @submit.prevent>
            <el-form-item label="年份">
              <el-input v-model="faces.year" placeholder="如 2026，留空=全部" clearable />
            </el-form-item>
            <el-form-item label="本次上限">
              <el-input-number
                v-model="faces.limit"
                :min="1"
                :max="50000"
                controls-position="right"
                class="limit-input"
              />
              <span class="inline-hint">留空=不限；OOM 时可设 500</span>
            </el-form-item>
            <el-form-item label="模式">
              <el-checkbox v-model="faces.refill">强制重跑（--refill）</el-checkbox>
            </el-form-item>
            <el-form-item label="完成后">
              <el-checkbox v-model="faces.sync_after">同步 SQLite 索引</el-checkbox>
            </el-form-item>
          </el-form>
          <el-button type="primary" :loading="loading.backfillFaces" @click="runBackfillFaces">
            重识别照片 people
          </el-button>
          <pre class="cli-hint">python tools/photo2json/main.py --backfill faces --refill [--year 2026] [--limit 500]</pre>
          <div v-if="results.faces" class="result-box">
            <div>backfill: 待处理 {{ results.faces.backfill.total }} · 更新 {{ results.faces.backfill.updated }} · 跳过 {{ results.faces.backfill.skipped }}</div>
            <div v-if="results.faces.sync">
              sync: 新增 {{ results.faces.sync.added }} · 更新 {{ results.faces.sync.updated }}
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ③ 索引与事件 -->
    <div class="section-label">索引与事件</div>
    <el-card class="tool-card sync-card" shadow="never">
      <template #header>
        <span class="card-title">🗂 索引</span>
      </template>
      <p class="step-hint">只改了 JSON、没跑上面两步时，单独同步索引即可。</p>
      <el-button :loading="loading.sync" @click="runSync">同步 SQLite 索引</el-button>
      <el-checkbox v-model="syncForce" class="force-check">强制全量（force）</el-checkbox>
      <pre class="cli-hint">python tools/memory_index/main.py sync</pre>
      <div v-if="results.sync" class="result-box">
        新增 {{ results.sync.added }} · 更新 {{ results.sync.updated }} · 跳过 {{ results.sync.skipped }}
      </div>
      <el-divider />
      <p class="step-hint">索引更新后重建出门事件（outing）；备注/故事会按锚点重挂。</p>
      <el-button :loading="loading.events" @click="runEventsSync">重建事件聚合</el-button>
      <pre class="cli-hint">python tools/memory_events/main.py sync</pre>
      <div v-if="results.events" class="result-box">
        outing {{ results.events.outing_events }} · 家 {{ results.events.home_events }} ·
        照片 {{ results.events.photos_in_events }}/{{ results.events.photos_with_ts }}
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = reactive({
  regeocode: false,
  rebuildIndex: false,
  backfillFaces: false,
  processPhotos: false,
  processVideos: false,
  backfillTranscript: false,
  sync: false,
  events: false,
})

const regeocode = reactive({
  limit: null,
  sync_after: true,
})

const faces = reactive({
  year: '',
  limit: 500,
  refill: true,
  sync_after: true,
})

const photos = reactive({
  year: '2026',
  limit: 50,
  sync_after: true,
})

const videos = reactive({
  year: '2026',
  month: '',
  limit: 50,
  no_ai: false,
  sync_after: true,
})

const transcript = reactive({
  year: '2026',
  month: '',
  limit: 10,
  force: false,
  sync_after: true,
})

const syncForce = ref(false)
const pendingLoading = ref(false)
const availableYears = ref(['2026'])
const availableMonths = ref([])

const emptyPendingKind = () => ({ total_files: 0, with_json: 0, pending: 0 })

const pending = reactive({
  photos: emptyPendingKind(),
  videos: emptyPendingKind(),
})

const results = reactive({
  regeocode: null,
  faces: null,
  photos: null,
  videos: null,
  transcript: null,
  sync: null,
  events: null,
})

const runtimeConfig = ref(null)
const jobCancelling = ref(false)

const job = reactive({
  running: false,
  kind: '',
  year: '',
  phase: '',
  current: 0,
  total: 0,
  current_file: '',
  success: 0,
  skipped: 0,
  failed: 0,
  message: '',
  error: '',
  cancelled: false,
  pending_at_start: 0,
  batch_limit: null,
  result: null,
})

let jobPollTimer = null

const mediaYear = computed(() => photos.year.trim() || videos.year.trim())

const mediaScopeLabel = computed(() => {
  const y = mediaYear.value
  if (!y) return '—'
  const m = videos.month.trim()
  if (m) return `${y}/${m}`
  return `${y} 年`
})

const videoCliPath = computed(() => {
  const y = videos.year.trim() || '2026'
  const m = videos.month.trim()
  return m ? `${y}/${m}` : y
})

const monthSelectHint = computed(() => {
  if (!availableMonths.value.length) {
    return '该年下暂无子文件夹，或 Desk 需重启'
  }
  return '清空=整年'
})

const transcriptMonths = ref([])

const jobProgressPercent = computed(() => {
  if (job.phase === 'sync') return 100
  const target = job.batch_limit != null
    ? Math.min(job.batch_limit, job.pending_at_start || job.batch_limit)
    : job.pending_at_start
  if (target > 0) {
    return Math.min(100, Math.round((job.success / target) * 100))
  }
  if (!job.total) return job.running ? 5 : 0
  return Math.min(100, Math.round((job.current / job.total) * 100))
})

const jobProgressText = computed(() => {
  const parts = []
  if (job.pending_at_start > 0) {
    const remain = Math.max(0, job.pending_at_start - job.success)
    parts.push(`开跑前待入库 ${job.pending_at_start} · 剩约 ${remain}`)
  }
  if (job.batch_limit != null) {
    parts.push(`本批 ${job.success}/${job.batch_limit}`)
  } else if (job.pending_at_start > 0) {
    parts.push(`本批成功 ${job.success}`)
  }
  parts.push(`跳过 ${job.skipped} · 失败 ${job.failed}`)
  if (job.total > 0) {
    parts.push(`目录扫描 ${job.current}/${job.total}`)
  }
  if (job.message && job.phase !== 'process') {
    parts.push(job.message)
  }
  return parts.join(' · ')
})

function jobKindLabel(kind) {
  if (kind === 'photos') return '照片 JSON'
  if (kind === 'videos') return '视频 JSON'
  if (kind === 'transcript') return '视频字幕'
  return kind || '维护任务'
}

function jobScopeLabel(scope) {
  if (!scope) return ''
  if (String(scope).includes('/')) return scope
  return `${scope} 年`
}

function applyJobStatus(data) {
  Object.assign(job, {
    running: !!data.running,
    kind: data.kind || '',
    year: data.year || '',
    phase: data.phase || '',
    current: data.current || 0,
    total: data.total || 0,
    current_file: data.current_file || '',
    success: data.success || 0,
    skipped: data.skipped || 0,
    failed: data.failed || 0,
    message: data.message || '',
    error: data.error || '',
    cancelled: !!data.cancelled,
    pending_at_start: data.pending_at_start || 0,
    batch_limit: data.batch_limit ?? null,
    result: data.result || null,
  })
  loading.processPhotos = data.running && data.kind === 'photos'
  loading.processVideos = data.running && data.kind === 'videos'
  loading.backfillTranscript = data.running && data.kind === 'transcript'
  if (!data.running && data.kind === 'transcript' && data.result) {
    results.transcript = data.result
  }
}

function stopJobPoll() {
  if (jobPollTimer) {
    clearInterval(jobPollTimer)
    jobPollTimer = null
  }
}

async function refreshPending() {
  const year = mediaYear.value
  if (!year) return
  pendingLoading.value = true
  try {
    const params = { year }
    const month = videos.month.trim()
    if (month) params.month = month
    const res = await axios.get('/api/tools/media-pending', { params })
    pending.photos = { ...emptyPendingKind(), ...res.data.photos }
    pending.videos = { ...emptyPendingKind(), ...res.data.videos }
    if (Array.isArray(res.data.available_years) && res.data.available_years.length) {
      availableYears.value = res.data.available_years
    }
    if (Array.isArray(res.data.available_months)) {
      availableMonths.value = res.data.available_months
      if (transcript.year.trim() === year) {
        transcriptMonths.value = res.data.available_months
      }
      if (videos.month && !availableMonths.value.includes(videos.month)) {
        videos.month = ''
        const retry = await axios.get('/api/tools/media-pending', { params: { year } })
        pending.photos = { ...emptyPendingKind(), ...retry.data.photos }
        pending.videos = { ...emptyPendingKind(), ...retry.data.videos }
      }
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '待入库统计失败')
  } finally {
    pendingLoading.value = false
  }
}

function onMediaYearChange() {
  const y = photos.year.trim()
  if (y) videos.year = y
  videos.month = ''
  refreshPending()
}

function onVideoYearChange() {
  const y = videos.year.trim()
  if (y && y !== photos.year) photos.year = y
  videos.month = ''
  refreshPending()
}

function onVideoMonthChange() {
  refreshPending()
}

async function loadTranscriptMonths() {
  const year = transcript.year.trim()
  if (!year) {
    transcriptMonths.value = []
    return
  }
  if (year === mediaYear.value && availableMonths.value.length) {
    transcriptMonths.value = [...availableMonths.value]
    return
  }
  try {
    const res = await axios.get('/api/tools/media-pending', { params: { year } })
    transcriptMonths.value = Array.isArray(res.data.available_months)
      ? res.data.available_months
      : []
  } catch {
    transcriptMonths.value = []
  }
}

function onTranscriptYearChange() {
  transcript.month = ''
  loadTranscriptMonths()
}

watch(
  () => videos.year,
  (y) => {
    if (y && y !== photos.year) photos.year = y
  },
)

function startJobPoll() {
  stopJobPoll()
  jobPollTimer = setInterval(async () => {
    try {
      const res = await axios.get('/api/tools/job-status')
      applyJobStatus(res.data)
      if (!res.data.running) {
        stopJobPoll()
        await refreshPending()
        if (res.data.error) {
          ElMessage.error(res.data.error)
        } else if (res.data.cancelled) {
          ElMessage.warning('本批已停止')
          if (res.data.kind === 'photos') results.photos = res.data.result
          if (res.data.kind === 'videos') results.videos = res.data.result
        } else if (res.data.result?.process) {
          const n = res.data.result.process.success
          const label = res.data.kind === 'videos' ? '条' : '张'
          ElMessage.success(`本批成功 ${n} ${label}`)
          if (res.data.kind === 'photos') results.photos = res.data.result
          if (res.data.kind === 'videos') results.videos = res.data.result
        }
      }
    } catch {
      /* 轮询失败不打断任务 */
    }
  }, 1500)
}

async function refreshJobStatus() {
  try {
    const res = await axios.get('/api/tools/job-status')
    applyJobStatus(res.data)
    if (res.data.running) startJobPoll()
  } catch {
    /* ignore */
  }
}

async function cancelJob() {
  jobCancelling.value = true
  try {
    await axios.post('/api/tools/job-cancel')
    ElMessage.info('已请求停止，当前这张/条完成后停')
    await refreshJobStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '停止失败')
  } finally {
    jobCancelling.value = false
  }
}

async function loadConfig() {
  try {
    const res = await axios.get('/api/tools/config')
    runtimeConfig.value = res.data
  } catch {
    runtimeConfig.value = null
  }
}

onMounted(async () => {
  await loadConfig()
  await refreshPending()
  await loadTranscriptMonths()
  await refreshJobStatus()
})

onUnmounted(stopJobPoll)

async function startMediaJob(endpoint, payload, kind) {
  if (job.running) {
    ElMessage.warning('已有任务在运行，请等当前任务完成')
    return
  }
  if (kind === 'photos') results.photos = null
  if (kind === 'videos') results.videos = null
  if (kind === 'transcript') results.transcript = null
  job.error = ''
  job.result = null
  try {
    const res = await axios.post(endpoint, payload)
    applyJobStatus(res.data.job || { running: true, kind, year: payload.year })
    startJobPoll()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '任务启动失败')
    loading.processPhotos = false
    loading.processVideos = false
    loading.backfillTranscript = false
  }
}

async function runRegeocode() {
  const isFull = regeocode.limit == null
  if (isFull) {
    try {
      await ElMessageBox.confirm(
        '将全库 regeocode，可能较久。建议先用地址缓存改完再跑。继续？',
        '应用地址缓存',
        { type: 'warning' },
      )
    } catch {
      return
    }
  }
  loading.regeocode = true
  results.regeocode = null
  try {
    const res = await axios.post('/api/tools/regeocode-locations', {
      limit: regeocode.limit || null,
      sync_after: regeocode.sync_after,
      normalize_after: false,
    })
    results.regeocode = res.data
    ElMessage.success('地址已写回 JSON')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'regeocode 失败')
  } finally {
    loading.regeocode = false
  }
}

async function runRebuildIndex() {
  loading.rebuildIndex = true
  try {
    const res = await axios.post('/api/tools/rebuild-face-index')
    ElMessage.success(`index 已重建（${res.data.people_count} 人）`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重建 index 失败')
  } finally {
    loading.rebuildIndex = false
  }
}

async function runBackfillFaces() {
  loading.backfillFaces = true
  results.faces = null
  try {
    const res = await axios.post('/api/tools/backfill-faces', {
      year: faces.year.trim(),
      limit: faces.limit || null,
      refill: faces.refill,
      sync_after: faces.sync_after,
    })
    results.faces = res.data
    ElMessage.success(`本批更新 ${res.data.backfill.updated} 张`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '人脸 backfill 失败')
  } finally {
    loading.backfillFaces = false
  }
}

async function runProcessPhotos(continueBatch = false) {
  const year = photos.year.trim()
  if (!year) {
    ElMessage.warning('请填写年份，如 2026')
    return
  }
  if (continueBatch && pending.photos.pending === 0) {
    ElMessage.info('该年照片已全部入库')
    return
  }
  await startMediaJob('/api/tools/process-photos', {
    year,
    limit: photos.limit || null,
    sync_after: photos.sync_after,
  }, 'photos')
}

async function runProcessVideos(continueBatch = false) {
  const year = videos.year.trim()
  if (!year) {
    ElMessage.warning('请填写年份，如 2026')
    return
  }
  const month = videos.month.trim()
  if (continueBatch && pending.videos.pending === 0) {
    ElMessage.info(month ? `该月/时段视频已全部入库` : '该年视频已全部入库')
    return
  }
  await startMediaJob('/api/tools/process-videos', {
    year,
    month,
    limit: videos.limit || null,
    no_ai: videos.no_ai,
    sync_after: videos.sync_after,
  }, 'videos')
}

async function runBackfillTranscript() {
  const year = transcript.year.trim()
  if (!year) {
    ElMessage.warning('请填写年份，如 2026')
    return
  }
  await startMediaJob('/api/tools/backfill-transcript', {
    year,
    month: transcript.month.trim(),
    limit: transcript.limit || null,
    force: transcript.force,
    sync_after: transcript.sync_after,
  }, 'transcript')
}

async function runSync() {
  loading.sync = true
  results.sync = null
  try {
    const res = await axios.post('/api/tools/sync-index', null, {
      params: { force: syncForce.value },
    })
    results.sync = res.data.stats
    ElMessage.success('索引已同步')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'sync 失败')
  } finally {
    loading.sync = false
  }
}

async function runEventsSync() {
  loading.events = true
  results.events = null
  try {
    const res = await axios.post('/api/events/sync')
    results.events = res.data
    ElMessage.success('事件已重建')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '事件重建失败')
  } finally {
    loading.events = false
  }
}
</script>

<style scoped>
.tools-container {
  height: 100%;
  min-height: 0;
  max-width: 1100px;
  overflow-x: hidden;
  overflow-y: auto;
  padding-bottom: 24px;
}

.intro {
  color: var(--muted);
  margin: 0 0 1.25rem;
  font-size: 0.95rem;
}

.config-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1.25rem;
}

.section-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0.5rem 0 0.75rem;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.tool-card {
  margin-bottom: 1.25rem;
  background: var(--panel);
  border-color: var(--border);
}

.section-card {
  border-color: rgba(91, 159, 212, 0.35);
}

.card-title {
  font-weight: 600;
}

.pending-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 1rem;
}

.pending-label {
  font-weight: 600;
  font-size: 0.95rem;
}

.pending-sub {
  opacity: 0.75;
  font-size: 0.85em;
}

.media-row {
  margin-top: 0.25rem;
}

.media-panel {
  padding: 0.25rem 0;
}

.transcript-panel {
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
}

.media-panel-title {
  font-weight: 600;
  margin-bottom: 0.35rem;
}

.media-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.step-hint {
  font-size: 0.85rem;
  color: var(--muted);
  margin: 0 0 1rem;
}

.cli-hint {
  margin: 0.75rem 0 0;
  padding: 0.5rem 0.65rem;
  font-size: 0.72rem;
  background: var(--bg);
  border-radius: 6px;
  color: var(--muted);
  overflow-x: auto;
}

.result-box {
  margin-top: 0.75rem;
  padding: 0.65rem 0.75rem;
  font-size: 0.85rem;
  background: rgba(91, 159, 212, 0.1);
  border-radius: 6px;
  border: 1px solid var(--border);
}

.inner-card {
  margin-bottom: 1rem;
  background: var(--bg);
  border-color: var(--border);
}

.job-card {
  background: var(--panel);
  border-color: var(--border);
}

.job-title {
  font-weight: 600;
  margin-bottom: 0.65rem;
}

.job-stats {
  margin-top: 0.65rem;
  font-size: 0.85rem;
  line-height: 1.5;
}

.job-file {
  margin-top: 0.35rem;
  font-size: 0.78rem;
  color: var(--muted);
  word-break: break-all;
}

.job-actions {
  margin-top: 0.75rem;
}

.job-hint {
  margin: 0.75rem 0 0;
}

.error-box {
  background: rgba(169, 68, 68, 0.12);
  border-color: rgba(169, 68, 68, 0.35);
}

.limit-input {
  width: 140px;
  margin-right: 0.5rem;
}

.year-select {
  width: 120px;
}

.month-select {
  width: 180px;
  margin-right: 0.5rem;
}

.inline-hint {
  font-size: 0.8rem;
  color: var(--muted);
}

.sync-card {
  max-width: 640px;
}

.force-check {
  margin-left: 1rem;
}
</style>
