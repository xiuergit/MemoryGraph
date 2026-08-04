<template>
  <div class="dedup-container">
    <div class="toolbar">
      <el-select v-model="year" placeholder="按年" clearable class="year-select">
        <el-option v-for="y in years" :key="y" :label="`${y} 年`" :value="y" />
      </el-select>
      <el-radio-group v-model="kind" size="small">
        <el-radio-button value="hash">字节重复</el-radio-button>
        <el-radio-button value="burst">连拍</el-radio-button>
        <el-radio-button value="all">全部</el-radio-button>
      </el-radio-group>
      <el-input-number
        v-model="burstSeconds"
        :min="0"
        :max="30"
        size="small"
        controls-position="right"
        class="burst-input"
      />
      <span class="muted">连拍间隔(秒)</span>
      <el-input-number
        v-model="limit"
        :min="0"
        :max="500"
        size="small"
        controls-position="right"
        class="limit-input"
      />
      <span class="muted">最多组数(0=不限)</span>
      <el-button type="primary" :loading="scanning" @click="scan">扫描候选</el-button>
      <el-button
        type="danger"
        plain
        :disabled="!selectedIds.length"
        :loading="deleting"
        @click="deleteSelected"
      >
        删除勾选 {{ selectedIds.length || '' }}
      </el-button>
    </div>

    <p class="hint">
      一组一组看：取消不需要删的勾选，再点「删除本组勾选」（只删仍勾着的）。KEEP 默认不勾。
      选年份也会带上无时间照片。也可顶栏「删除勾选」。删除进 data/.trash/。
    </p>

    <div v-if="summary" class="summary">
      扫描 {{ summary.scanned }} 张 · 字节重复 {{ summary.exact_groups }} 组 /
      {{ summary.exact_extra }} 张 · 连拍 {{ summary.burst_groups }} 组 /
      {{ summary.burst_extra }} 张
      <template v-if="summary.untimed_count">
        · 无时间 {{ summary.untimed_count }} · 近相似 {{ summary.near_groups || 0 }} 组
      </template>
      <template v-if="summary.missing_files"> · 缺原图 {{ summary.missing_files }}</template>
      <template v-if="groups.length && (summary.exact_groups + summary.burst_groups) > groups.length">
        · 本页显示 {{ groups.length }} 组
      </template>
    </div>

    <div v-loading="scanning" class="groups-scroll">
      <el-empty
        v-if="!scanning && scannedOnce && !groups.length && !untimedPhotos.length"
        description="没有候选组，可换年份或类型再扫"
      />

      <section v-for="(group, gi) in groups" :key="group.group_id" class="group-card">
        <header class="group-head">
          <el-tag
            size="small"
            :type="
              group.kind === 'exact_hash'
                ? 'danger'
                : group.kind === 'near_hash'
                  ? 'info'
                  : 'warning'
            "
          >
            {{
              group.kind === 'exact_hash'
                ? '字节重复'
                : group.kind === 'near_hash'
                  ? '近相似'
                  : '连拍'
            }}
          </el-tag>
          <span class="group-title">{{ groupLabel(gi, group) }}</span>
          <span class="muted reason">{{ group.reason }}</span>
          <el-button
            size="small"
            type="danger"
            plain
            :loading="deletingGroupId === group.group_id"
            :disabled="!groupSelectedCount(group) || deleting"
            @click="deleteGroupSuggested(group)"
          >
            删除本组勾选 ({{ groupSelectedCount(group) }})
          </el-button>
          <el-button size="small" text @click="selectSuggested(group)">勾选建议</el-button>
          <el-button size="small" text @click="clearGroup(group)">清空勾选</el-button>
        </header>

        <div class="photo-row">
          <div
            v-for="photo in group.candidates"
            :key="photo.photo_id"
            class="photo-card"
            :class="{
              keep: photo.photo_id === group.keep_photo_id,
              selected: isSelected(photo.photo_id),
            }"
          >
            <label class="check-wrap" @click.stop>
              <el-checkbox
                :model-value="isSelected(photo.photo_id)"
                :disabled="photo.photo_id === group.keep_photo_id && group.kind === 'exact_hash'"
                @update:model-value="(v) => toggleSelect(photo.photo_id, !!v)"
              />
              <span class="badge">
                {{ photo.photo_id === group.keep_photo_id ? 'KEEP' : 'drop?' }}
              </span>
            </label>
            <div
              class="thumb"
              @click.stop="
                !(photo.photo_id === group.keep_photo_id && group.kind === 'exact_hash') &&
                  toggleSelect(photo.photo_id, !isSelected(photo.photo_id))
              "
            >
              <img
                v-if="previewPath(photo)"
                :src="previewUrl(previewPath(photo))"
                :alt="photo.photo_id"
                loading="lazy"
              />
              <div v-else class="no-preview">无预览</div>
            </div>
            <div class="meta" :title="photo.photo_id">
              <button type="button" class="id-link" @click="emit('view-detail', photo.photo_id)">
                {{ shortId(photo.photo_id) }}
              </button>
              <div class="meta-line">{{ photo.timestamp || '无时间' }}</div>
              <div class="meta-line">{{ photo.location || '无地址' }}</div>
              <div class="meta-line">
                {{ (photo.people || []).join('、') || '无人' }}
                · {{ sizeLabel(photo.file_size) }}
              </div>
              <div v-if="!photo.timestamp" class="untimed-tag">无时间 · 可补</div>
              <div v-if="photo.quality_computed" class="quality">
                画质 {{ Math.round(photo.quality_score) }}
              </div>
              <div v-if="flagText(photo)" class="flags">{{ flagText(photo) }}</div>
            </div>
          </div>
        </div>
      </section>

      <section v-if="untimedPhotos.length" class="group-card untimed-card">
        <header class="group-head">
          <el-tag size="small" type="info">无时间</el-tag>
          <span class="group-title">
            近哈希相邻 · 展示 {{ untimedPhotos.length }}
            <template v-if="summary?.untimed_count > untimedPhotos.length">
              / 共 {{ summary.untimed_count }}
            </template>
          </span>
          <span class="muted reason">
            相似图挨在一起，方便连着补时间/地址；上方「近相似」组可删重复。
          </span>
          <el-button size="small" text type="primary" @click="selectAllUntimed">全选本页</el-button>
          <el-button size="small" text @click="clearUntimedSelection">清空勾选</el-button>
        </header>
        <div class="photo-row">
          <template v-for="(photo, ui) in untimedPhotos" :key="'u-' + photo.photo_id">
            <div
              v-if="untimedClusterBreak(ui)"
              class="cluster-break"
            >
              {{ photo.near_cluster ? `相似簇 · ${photo.near_cluster}` : '其余（无相似组）' }}
            </div>
            <div
              class="photo-card"
              :class="{
                selected: isSelected(photo.photo_id),
                clustered: !!photo.near_cluster,
              }"
            >
              <label class="check-wrap" @click.stop>
                <el-checkbox
                  :model-value="isSelected(photo.photo_id)"
                  @update:model-value="(v) => toggleSelect(photo.photo_id, !!v)"
                />
                <span class="badge">{{ photo.near_cluster ? '相似' : '无时间' }}</span>
              </label>
              <div
                class="thumb"
                @click.stop="toggleSelect(photo.photo_id, !isSelected(photo.photo_id))"
              >
                <img
                  v-if="previewPath(photo)"
                  :src="previewUrl(previewPath(photo))"
                  :alt="photo.photo_id"
                  loading="lazy"
                />
                <div v-else class="no-preview">无预览</div>
              </div>
              <div class="meta" :title="photo.photo_id">
                <button type="button" class="id-link" @click="emit('view-detail', photo.photo_id)">
                  {{ shortId(photo.photo_id) }}
                </button>
                <div class="meta-line">{{ photo.location || '无地址 · 可补' }}</div>
                <div class="meta-line">
                  {{ (photo.people || []).join('、') || '无人' }}
                  · {{ sizeLabel(photo.file_size) }}
                </div>
                <button
                  type="button"
                  class="id-link fill-link"
                  @click="emit('view-detail', photo.photo_id)"
                >
                  打开详情补时间/地址
                </button>
              </div>
            </div>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const emit = defineEmits(['view-detail'])

const years = ref([])
const year = ref('2024')
const kind = ref('hash')
const burstSeconds = ref(3)
const limit = ref(50)
const scanning = ref(false)
const deleting = ref(false)
const deletingGroupId = ref('')
const scannedOnce = ref(false)
const summary = ref(null)
const groups = ref([])
const untimedPhotos = ref([])
const selected = ref(new Set())

const selectedIds = computed(() => [...selected.value])

function isSelected(id) {
  return selected.value.has(id)
}

function toggleSelect(id, on) {
  const next = new Set(selected.value)
  if (on) next.add(id)
  else next.delete(id)
  selected.value = next
}

function selectSuggested(group) {
  const next = new Set(selected.value)
  for (const id of group.drop_photo_ids || []) next.add(id)
  selected.value = next
}

function clearGroup(group) {
  const next = new Set(selected.value)
  for (const p of group.candidates || []) next.delete(p.photo_id)
  selected.value = next
}

function selectAllUntimed() {
  const next = new Set(selected.value)
  for (const p of untimedPhotos.value) next.add(p.photo_id)
  selected.value = next
}

function clearUntimedSelection() {
  const next = new Set(selected.value)
  for (const p of untimedPhotos.value) next.delete(p.photo_id)
  selected.value = next
}

function previewPath(photo) {
  return photo.source_path || photo.resolved_path || ''
}

function previewUrl(path) {
  return `/api/preview?path=${encodeURIComponent(path)}&size=320`
}

function shortId(id) {
  if (!id) return ''
  return id.length > 28 ? `${id.slice(0, 12)}…${id.slice(-10)}` : id
}

function sizeLabel(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

function flagText(photo) {
  const flags = []
  if (photo.manual_people) flags.push('手改人物')
  if (photo.manual_location) flags.push('手改地址')
  if (photo.overlay_anchor) flags.push('事件锚点')
  if (photo.face_detected) flags.push('人脸')
  return flags.join(' · ')
}

function groupLabel(index, group) {
  const prefix =
    group.kind === 'exact_hash' ? 'E' : group.kind === 'near_hash' ? 'N' : 'B'
  return `${prefix}${index + 1} · ${group.candidates?.length || 0} 张`
}

function untimedClusterBreak(index) {
  const list = untimedPhotos.value
  const cur = list[index]
  if (!cur) return false
  if (index === 0) return true
  const prev = list[index - 1]
  return (cur.near_cluster || '') !== (prev.near_cluster || '')
}

async function loadYears() {
  try {
    const res = await axios.get('/api/memory/years')
    years.value = res.data.years || []
    if (!year.value && years.value.length) {
      year.value = String(years.value[0])
    }
  } catch {
    years.value = []
  }
}

function applyDefaultSelection(list) {
  const next = new Set()
  for (const g of list) {
    for (const id of g.drop_photo_ids || []) next.add(id)
  }
  selected.value = next
}

function groupSelectedCount(group) {
  return groupSelectedIds(group).length
}

function groupSelectedIds(group) {
  const keepId = group.keep_photo_id || ''
  const ids = []
  for (const p of group.candidates || []) {
    if (!p?.photo_id) continue
    if (p.photo_id === keepId) continue
    if (selected.value.has(p.photo_id)) ids.push(p.photo_id)
  }
  return ids
}

function removeGroupFromList(group, deletedIds) {
  const deleted = new Set(deletedIds || group.drop_photo_ids || [])
  const next = new Set(selected.value)
  for (const id of deleted) next.delete(id)
  selected.value = next

  const remaining = (group.candidates || []).filter((p) => !deleted.has(p.photo_id))
  const stillDrops = remaining.filter((p) => p.photo_id !== group.keep_photo_id)

  if (stillDrops.length === 0) {
    groups.value = groups.value.filter((g) => g.group_id !== group.group_id)
    if (summary.value) {
      const n = deleted.size
      if (group.kind === 'exact_hash') {
        summary.value = {
          ...summary.value,
          exact_groups: Math.max(0, (summary.value.exact_groups || 0) - 1),
          exact_extra: Math.max(0, (summary.value.exact_extra || 0) - n),
        }
      } else if (group.kind === 'near_hash') {
        summary.value = {
          ...summary.value,
          near_groups: Math.max(0, (summary.value.near_groups || 0) - 1),
          near_extra: Math.max(0, (summary.value.near_extra || 0) - n),
        }
      } else {
        summary.value = {
          ...summary.value,
          burst_groups: Math.max(0, (summary.value.burst_groups || 0) - 1),
          burst_extra: Math.max(0, (summary.value.burst_extra || 0) - n),
        }
      }
    }
    // 同步从无时间列表去掉已删
    if (untimedPhotos.value.length) {
      untimedPhotos.value = untimedPhotos.value.filter((p) => !deleted.has(p.photo_id))
    }
    return
  }

  // 部分删除：留在列表里，更新候选（替换数组项以触发视图刷新）
  const updated = {
    ...group,
    candidates: remaining,
    drop_photo_ids: stillDrops.map((p) => p.photo_id),
  }
  groups.value = groups.value.map((g) => (g.group_id === group.group_id ? updated : g))
  if (untimedPhotos.value.length) {
    untimedPhotos.value = untimedPhotos.value.filter((p) => !deleted.has(p.photo_id))
  }
  if (summary.value) {
    const n = deleted.size
    if (group.kind === 'exact_hash') {
      summary.value = {
        ...summary.value,
        exact_extra: Math.max(0, (summary.value.exact_extra || 0) - n),
      }
    } else if (group.kind === 'near_hash') {
      summary.value = {
        ...summary.value,
        near_extra: Math.max(0, (summary.value.near_extra || 0) - n),
      }
    } else {
      summary.value = {
        ...summary.value,
        burst_extra: Math.max(0, (summary.value.burst_extra || 0) - n),
      }
    }
  }
}

async function deletePhotoIds(ids, { confirmTitle, confirmMsg }) {
  if (!ids.length) return false
  try {
    await ElMessageBox.confirm(confirmMsg, confirmTitle, {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return false
  }

  const res = await axios.post('/api/delete/batch', { photo_ids: ids })
  const deletedCount = res.data.deleted_count || 0
  const failedCount = res.data.failed_count || 0
  if (failedCount > 0) {
    const detail = (res.data.failed || [])
      .map((item) => `${item.photo_id}: ${item.error}`)
      .join('\n')
    ElMessage.warning(`已删除 ${deletedCount}，失败 ${failedCount}\n${detail}`)
  } else {
    ElMessage.success(`已删除 ${deletedCount} 张`)
  }
  return deletedCount > 0
}

async function deleteGroupSuggested(group) {
  const ids = groupSelectedIds(group)
  if (!ids.length) {
    ElMessage.info('请先勾选要删除的照片（可点「勾选建议」后再取消不想删的）')
    return
  }
  const keepId = group.keep_photo_id || 'KEEP'
  deletingGroupId.value = group.group_id
  try {
    const ok = await deletePhotoIds(ids, {
      confirmTitle: '删除本组勾选',
      confirmMsg:
        `保留 ${keepId}\n删除勾选的 ${ids.length} 张？\n\n原图 + JSON → data/.trash/`,
    })
    if (ok) {
      removeGroupFromList(group, ids)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '删除失败')
  } finally {
    deletingGroupId.value = ''
  }
}

async function scan() {
  scanning.value = true
  scannedOnce.value = true
  try {
    const res = await axios.get('/api/dedup/report', {
      params: {
        year: year.value || '',
        kind: kind.value,
        burst_seconds: burstSeconds.value,
        limit: limit.value,
      },
      timeout: 300000,
    })
    summary.value = {
      scanned: res.data.scanned,
      missing_files: res.data.missing_files,
      exact_groups: res.data.exact_groups,
      exact_extra: res.data.exact_extra,
      burst_groups: res.data.burst_groups,
      burst_extra: res.data.burst_extra,
      untimed_count: res.data.untimed_count || 0,
      near_groups: res.data.near_groups || 0,
      near_extra: res.data.near_extra || 0,
    }
    groups.value = res.data.groups || []
    untimedPhotos.value = res.data.untimed_photos || []
    applyDefaultSelection(groups.value)
    if (!groups.value.length && !untimedPhotos.value.length) {
      ElMessage.info('没有候选组')
    } else {
      const parts = []
      if (groups.value.length) parts.push(`${groups.value.length} 组`)
      if (summary.value.near_groups) parts.push(`近相似 ${summary.value.near_groups}`)
      if (summary.value.untimed_count) parts.push(`无时间 ${summary.value.untimed_count}`)
      ElMessage.success(`找到 ${parts.join(' · ')}`)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '扫描失败')
    groups.value = []
    untimedPhotos.value = []
    summary.value = null
  } finally {
    scanning.value = false
  }
}

async function deleteSelected() {
  const ids = selectedIds.value
  if (!ids.length) return
  deleting.value = true
  try {
    const ok = await deletePhotoIds(ids, {
      confirmTitle: '删除勾选',
      confirmMsg: `确定删除勾选的 ${ids.length} 张？\n\n原图 + memory JSON → data/.trash/`,
    })
    if (ok) {
      await scan()
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '删除失败')
  } finally {
    deleting.value = false
  }
}

onMounted(loadYears)
</script>

<style scoped>
.dedup-container {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  flex-shrink: 0;
}

.year-select {
  width: 110px;
}

.burst-input,
.limit-input {
  width: 100px;
}

.muted {
  color: var(--muted);
  font-size: 0.85rem;
}

.hint {
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
  flex-shrink: 0;
}

.summary {
  flex-shrink: 0;
  font-size: 0.9rem;
  padding: 0.5rem 0.75rem;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.groups-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding-bottom: 1rem;
}

.group-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
  padding: 0.75rem;
}

.group-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.65rem;
}

.group-title {
  font-weight: 600;
}

.reason {
  flex: 1;
  min-width: 12rem;
  font-size: 0.8rem;
}

.photo-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
}

.photo-card {
  width: 148px;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg, #111);
}

.photo-card.keep {
  border-color: #3d8b5a;
}

.photo-card.selected {
  outline: 2px solid #c45656;
}

.check-wrap {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.4rem;
  font-size: 0.75rem;
  cursor: pointer;
}

.badge {
  font-weight: 600;
  color: var(--muted);
}

.photo-card.keep .badge {
  color: #3d8b5a;
}

.thumb {
  height: 110px;
  background: #1a1a1a;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.no-preview {
  color: var(--muted);
  font-size: 0.8rem;
}

.meta {
  padding: 0.35rem 0.45rem 0.5rem;
  font-size: 0.72rem;
  line-height: 1.35;
  color: var(--muted);
}

.id-link {
  border: none;
  background: none;
  padding: 0;
  color: var(--el-color-primary);
  cursor: pointer;
  font-size: 0.72rem;
  text-align: left;
  word-break: break-all;
}

.meta-line {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.flags {
  margin-top: 0.15rem;
  color: #c9a227;
}

.quality {
  margin-top: 0.15rem;
  color: #3d8b5a;
  font-weight: 600;
}

.untimed-tag {
  margin-top: 0.15rem;
  color: #6b8cae;
  font-weight: 600;
}

.untimed-card {
  border-style: dashed;
}

.fill-link {
  margin-top: 0.25rem;
  display: inline-block;
}

.cluster-break {
  flex-basis: 100%;
  width: 100%;
  margin: 0.5rem 0 0.15rem;
  padding: 0.25rem 0.4rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: #6b8cae;
  border-bottom: 1px dashed var(--border);
}

.photo-card.clustered {
  border-color: #5a7a9a;
}
</style>
