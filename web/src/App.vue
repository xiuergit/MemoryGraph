<template>
  <div class="app-container">
    <header class="app-header">
      <h1>MemoryGraph Inspector</h1>
      <p>检查 memory JSON · 记忆问答 · 事件 · 地址缓存 · 人脸库 · 维护工具</p>
    </header>

    <main class="app-main">
      <el-tabs v-model="activeTab" type="border-card" class="tabs-container">
        <el-tab-pane label="列表" name="list">
          <MemoryList @view-detail="openDetail" />
        </el-tab-pane>

        <el-tab-pane label="问答" name="ask">
          <MemoryAsk @view-detail="openDetail" />
        </el-tab-pane>

        <el-tab-pane label="事件" name="events">
          <MemoryEvents @view-detail="openDetail" />
        </el-tab-pane>

        <el-tab-pane label="详情" name="detail">
          <MemoryDetail v-if="selectedPhotoId" :photo-id="selectedPhotoId" />
          <div v-else class="empty-hint">
            <el-empty description="请从列表、问答或事件页选择一条记录查看详情" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="批量改地址" name="batch-edit">
          <MemoryBatchEdit @view-detail="openDetail" />
        </el-tab-pane>

        <el-tab-pane label="地址缓存" name="geocode-cache">
          <GeocodeCache @view-detail="openDetail" />
        </el-tab-pane>

        <el-tab-pane label="人脸库" name="face-registry">
          <FaceRegistry />
        </el-tab-pane>

        <el-tab-pane label="维护工具" name="tools">
          <MaintenanceTools />
        </el-tab-pane>

        <el-tab-pane label="验证" name="validate">
          <MemoryValidate />
        </el-tab-pane>

        <el-tab-pane label="健康报告" name="stats">
          <MemoryStats />
        </el-tab-pane>
      </el-tabs>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import MemoryList from './components/MemoryList.vue'
import MemoryAsk from './components/MemoryAsk.vue'
import MemoryEvents from './components/MemoryEvents.vue'
import MemoryDetail from './components/MemoryDetail.vue'
import MemoryBatchEdit from './components/MemoryBatchEdit.vue'
import GeocodeCache from './components/GeocodeCache.vue'
import MemoryValidate from './components/MemoryValidate.vue'
import MemoryStats from './components/MemoryStats.vue'
import MaintenanceTools from './components/MaintenanceTools.vue'
import FaceRegistry from './components/FaceRegistry.vue'

const activeTab = ref('list')
const selectedPhotoId = ref('')

function openDetail(photoId) {
  selectedPhotoId.value = photoId
  activeTab.value = 'detail'
}
</script>

<style scoped>
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.app-header {
  flex-shrink: 0;
  padding: 1.5rem 2rem;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.app-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.app-header p {
  margin: 0.4rem 0 0;
  color: var(--muted);
  font-size: 0.9rem;
}

.app-main {
  flex: 1;
  min-height: 0;
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tabs-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tabs-container :deep(.el-tabs__header) {
  flex-shrink: 0;
}

.tabs-container :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 12px;
  display: flex;
  flex-direction: column;
}

.tabs-container :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.tabs-container :deep(.el-tabs__body),
.tabs-container :deep(.el-tabs__content > .el-tab-pane) {
  height: 100%;
}

.empty-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}
</style>
