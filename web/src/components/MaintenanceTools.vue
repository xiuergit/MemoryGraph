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
          <el-button
            type="primary"
            :loading="loading.regeocode"
            @click="runRegeocode"
          >
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

          <el-button
            :loading="loading.rebuildIndex"
            @click="runRebuildIndex"
          >
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
          <el-button
            type="primary"
            :loading="loading.backfillFaces"
            @click="runBackfillFaces"
          >
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
import { reactive, ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = reactive({
  regeocode: false,
  rebuildIndex: false,
  backfillFaces: false,
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

const syncForce = ref(false)

const results = reactive({
  regeocode: null,
  faces: null,
  sync: null,
  events: null,
})

const runtimeConfig = ref(null)

async function loadConfig() {
  try {
    const res = await axios.get('/api/tools/config')
    runtimeConfig.value = res.data
  } catch {
    runtimeConfig.value = null
  }
}

onMounted(loadConfig)

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

.tool-card {
  margin-bottom: 1.25rem;
  background: var(--panel);
  border-color: var(--border);
}

.card-title {
  font-weight: 600;
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

.limit-input {
  width: 140px;
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
