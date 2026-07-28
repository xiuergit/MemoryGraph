<template>
  <div class="stats-container" v-loading="loading">
    <div v-if="stats" class="stats-content">
      <div class="refresh-bar">
        <el-button @click="loadStats">刷新数据</el-button>
      </div>

      <el-row :gutter="20" class="stats-row">
        <el-col :span="6">
          <el-card class="stat-card">
            <div class="stat-icon">📷</div>
            <div class="stat-value">{{ stats.memory.total }}</div>
            <div class="stat-label">Memory JSON 总数</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card class="stat-card warning" v-if="stats.memory.bad_json">
            <div class="stat-icon">⚠️</div>
            <div class="stat-value">{{ stats.memory.bad_json }}</div>
            <div class="stat-label">损坏的 JSON</div>
          </el-card>
          <el-card class="stat-card success" v-else>
            <div class="stat-icon">✅</div>
            <div class="stat-value">0</div>
            <div class="stat-label">损坏的 JSON</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card class="stat-card">
            <div class="stat-icon">👤</div>
            <div class="stat-value">{{ stats.memory.face_detected }}</div>
            <div class="stat-label">检测到人脸</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card class="stat-card">
            <div class="stat-icon">🏠</div>
            <div class="stat-value">{{ stats.memory.has_location }}</div>
            <div class="stat-label">有地点信息</div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20" class="stats-row">
        <el-col :span="6">
          <el-card class="stat-card">
            <div class="stat-icon">👥</div>
            <div class="stat-value">{{ stats.memory.people_nonempty }}</div>
            <div class="stat-label">人物非空</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card class="stat-card warning" v-if="stats.memory.needs_faces">
            <div class="stat-icon">🔍</div>
            <div class="stat-value">{{ stats.memory.needs_faces }}</div>
            <div class="stat-label">有脸未识别</div>
          </el-card>
          <el-card class="stat-card success" v-else>
            <div class="stat-icon">✅</div>
            <div class="stat-value">0</div>
            <div class="stat-label">有脸未识别</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card class="stat-card">
            <div class="stat-icon">👁️</div>
            <div class="stat-value">{{ stats.memory.vision_filled }}</div>
            <div class="stat-label">Vision 已补</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card class="stat-card" v-if="stats.memory.vision_empty">
            <div class="stat-icon">📝</div>
            <div class="stat-value">{{ stats.memory.vision_empty }}</div>
            <div class="stat-label">Vision 待补</div>
          </el-card>
          <el-card class="stat-card success" v-else>
            <div class="stat-icon">✅</div>
            <div class="stat-value">0</div>
            <div class="stat-label">Vision 待补</div>
          </el-card>
        </el-col>
      </el-row>

      <div class="stats-section">
        <h3>按年分布</h3>
        <div class="year-chart">
          <div
            v-for="(count, year) in sortedYears"
            :key="year"
            class="year-bar-wrapper"
          >
            <div class="year-label">{{ year }}</div>
            <div class="year-bar-container">
              <div
                class="year-bar"
                :style="{ width: getBarWidth(count) + '%' }"
              ></div>
            </div>
            <div class="year-count">{{ count }}</div>
          </div>
        </div>
      </div>

      <div class="stats-section">
        <h3>人物排名</h3>
        <el-table :data="peopleRank" stripe size="small" max-height="300">
          <el-table-column prop="person_id" label="人物 ID" width="150" />
          <el-table-column prop="count" label="出现次数" width="100" />
          <el-table-column label="占比">
            <template #default="scope">
              <div class="percentage-bar">
                <div
                  class="percentage-fill"
                  :style="{ width: getPercentage(scope.row.count) + '%' }"
                ></div>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="stats-section">
        <h3>人脸库</h3>
        <el-row :gutter="20">
          <el-col :span="4">
            <el-card class="mini-card">
              <div class="mini-value">{{ stats.faces.registry_count }}</div>
              <div class="mini-label">Registry 条目</div>
            </el-card>
          </el-col>
          <el-col :span="4">
            <el-card class="mini-card">
              <div class="mini-value">{{ stats.faces.folder_count }}</div>
              <div class="mini-label">文件夹数</div>
            </el-card>
          </el-col>
          <el-col :span="4">
            <el-card class="mini-card">
              <div class="mini-value">{{ stats.faces.total_ref_images }}</div>
              <div class="mini-label">参考照片</div>
            </el-card>
          </el-col>
        </el-row>
        <div v-if="stats.faces.registry_no_folder.length" class="issue-list">
          <h4>Registry 无文件夹</h4>
          <el-tag
            v-for="item in stats.faces.registry_no_folder"
            :key="item[0]"
            type="danger"
            size="small"
          >
            {{ item[0] }} → {{ item[1] }}
          </el-tag>
        </div>
        <div v-if="stats.faces.folder_no_registry.length" class="issue-list">
          <h4>文件夹无 Registry</h4>
          <el-tag
            v-for="item in stats.faces.folder_no_registry"
            :key="item[0]"
            type="warning"
            size="small"
          >
            {{ item[0] }} ({{ item[1] }}张)
          </el-tag>
        </div>
      </div>

      <div class="stats-section">
        <h3>SQLite 索引</h3>
        <div v-if="stats.sqlite.exists">
          <el-row :gutter="20">
            <el-col :span="4">
              <el-card class="mini-card">
                <div class="mini-value">{{ stats.sqlite.photos }}</div>
                <div class="mini-label">照片数</div>
              </el-card>
            </el-col>
            <el-col :span="4">
              <el-card class="mini-card">
                <div class="mini-value">{{ stats.sqlite.distinct_people }}</div>
                <div class="mini-label">人物数</div>
              </el-card>
            </el-col>
            <el-col :span="4">
              <el-card class="mini-card">
                <div class="mini-value">{{ stats.sqlite.with_face }}</div>
                <div class="mini-label">有人脸</div>
              </el-card>
            </el-col>
          </el-row>
          <div v-if="stats.sqlite.top_people.length">
            <h4>索引人物排名</h4>
            <el-table :data="stats.sqlite.top_people" stripe size="small" max-height="200">
              <el-table-column prop="person_id" label="人物 ID" width="150" />
              <el-table-column prop="count" label="次数" width="100" />
            </el-table>
          </div>
        </div>
        <div v-else class="empty-sqlite">
          <el-empty description="未找到 memorygraph.db，请先执行 memory_index sync" />
        </div>
      </div>
    </div>

    <div v-else-if="!loading" class="stats-empty">
      <el-empty description="点击刷新加载统计数据" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const loading = ref(false)
const stats = ref(null)

const sortedYears = computed(() => {
  if (!stats.value) return []
  return Object.entries(stats.value.memory.by_year)
    .sort((a, b) => b[0].localeCompare(a[0]))
})

const peopleRank = computed(() => {
  if (!stats.value) return []
  return Object.entries(stats.value.memory.people_ids).map(([person_id, count]) => ({
    person_id,
    count,
  }))
})

const maxYearCount = computed(() => {
  if (!stats.value) return 1
  const counts = Object.values(stats.value.memory.by_year)
  return Math.max(...counts, 1)
})

const maxPeopleCount = computed(() => {
  if (!stats.value) return 1
  const counts = Object.values(stats.value.memory.people_ids)
  return Math.max(...counts, 1)
})

async function loadStats() {
  loading.value = true
  try {
    const res = await axios.get('/api/memory/stats')
    stats.value = res.data
  } catch (error) {
    console.error('加载统计失败:', error)
    stats.value = null
  } finally {
    loading.value = false
  }
}

function getBarWidth(count) {
  return (count / maxYearCount.value) * 100
}

function getPercentage(count) {
  return (count / maxPeopleCount.value) * 100
}

onMounted(loadStats)
</script>

<style scoped>
.stats-container {
  height: 100%;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-bottom: 24px;
}

.refresh-bar {
  margin-bottom: 1.5rem;
}

.stats-row {
  margin-bottom: 1rem;
}

.stat-card {
  text-align: center;
  padding: 1rem;
}

.stat-card.success {
  border-color: #67c23a;
}

.stat-card.warning {
  border-color: #e6a23c;
}

.stat-icon {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.stat-value {
  font-size: 2rem;
  font-weight: 700;
  margin-bottom: 0.3rem;
}

.stat-label {
  font-size: 0.85rem;
  color: var(--muted);
}

.stats-section {
  margin-top: 2rem;
}

.stats-section h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.stats-section h4 {
  margin: 1rem 0 0.5rem;
  font-size: 0.9rem;
  color: var(--muted);
}

.year-chart {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.year-bar-wrapper {
  flex: 1;
  min-width: 100px;
}

.year-label {
  font-size: 0.8rem;
  color: var(--muted);
  text-align: center;
  margin-bottom: 0.3rem;
}

.year-bar-container {
  height: 24px;
  background: var(--border);
  border-radius: 4px;
  overflow: hidden;
}

.year-bar {
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.year-count {
  font-size: 0.8rem;
  text-align: center;
  margin-top: 0.3rem;
}

.percentage-bar {
  height: 12px;
  background: var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.percentage-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 6px;
  transition: width 0.3s ease;
}

.mini-card {
  text-align: center;
  padding: 0.75rem;
}

.mini-value {
  font-size: 1.2rem;
  font-weight: 600;
}

.mini-label {
  font-size: 0.75rem;
  color: var(--muted);
}

.issue-list {
  margin-top: 0.5rem;
}

.empty-sqlite {
  padding: 2rem;
}

.stats-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}
</style>
