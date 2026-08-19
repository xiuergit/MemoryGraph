<template>
  <div class="validate-container">
    <div class="validate-header">
      <div class="input-row">
        <el-input
          v-model="photoId"
          placeholder="输入 photo_id 验证单个文件（留空验证全部）"
          clearable
          class="id-input"
        />
        <el-button type="primary" @click="runValidate">开始验证</el-button>
      </div>
    </div>

    <div v-if="result" class="validate-result">
      <div class="result-summary">
        <div class="summary-item">
          <span class="summary-label">总数</span>
          <span class="summary-value">{{ result.total }}</span>
        </div>
        <div class="summary-item success">
          <span class="summary-label">通过</span>
          <span class="summary-value">{{ result.valid }}</span>
        </div>
        <div class="summary-item error">
          <span class="summary-label">失败</span>
          <span class="summary-value">{{ result.invalid }}</span>
        </div>
      </div>

      <div class="result-tabs">
        <el-tabs v-model="resultTab" type="border-card">
          <el-tab-pane label="全部" name="all">
            <el-table :data="result.results" stripe size="small">
              <el-table-column prop="photo_id" label="ID" width="180" />
              <el-table-column label="状态" width="100" align="center">
                <template #default="scope">
                  <el-tag :type="scope.row.valid ? 'success' : 'danger'">
                    {{ scope.row.valid ? '通过' : '失败' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="错误信息">
                <template #default="scope">
                  <el-button
                    v-if="scope.row.errors.length"
                    type="text"
                    size="small"
                    @click="showErrors(scope.row)"
                  >
                    查看错误
                  </el-button>
                  <span v-else>-</span>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="失败" name="invalid">
            <el-table :data="invalidResults" stripe size="small">
              <el-table-column prop="photo_id" label="ID" width="180" />
              <el-table-column label="状态" width="100" align="center">
                <el-tag type="danger">失败</el-tag>
              </el-table-column>
              <el-table-column label="错误信息">
                <template #default="scope">
                  <el-button
                    type="text"
                    size="small"
                    @click="showErrors(scope.row)"
                  >
                    查看错误
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!invalidResults.length" description="无失败记录" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>

    <div v-else class="validate-empty">
      <el-empty description="点击「开始验证」检查 JSON 是否符合 Schema" />
    </div>

    <el-dialog
      v-model="errorDialogVisible"
      :title="`错误详情 - ${currentError?.photo_id}`"
      width="60%"
    >
      <div class="error-details">
        <div
          v-for="(error, index) in currentError?.errors || []"
          :key="index"
          class="error-item"
        >
          {{ error }}
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import axios from 'axios'

const photoId = ref('')
const result = ref(null)
const resultTab = ref('all')
const errorDialogVisible = ref(false)
const currentError = ref(null)

const invalidResults = computed(() => {
  if (!result.value) return []
  return result.value.results.filter(r => !r.valid)
})

async function runValidate() {
  try {
    const params = {}
    if (photoId.value.trim()) {
      params.photo_id = photoId.value.trim()
    }
    const res = await axios.get('/api/memory/validate', { params })
    result.value = res.data
  } catch (error) {
    console.error('验证失败:', error)
  }
}

function showErrors(row) {
  currentError.value = row
  errorDialogVisible.value = true
}
</script>

<style scoped>
.validate-container {
  height: 100%;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-bottom: 24px;
}

.validate-header {
  margin-bottom: 1.5rem;
}

.input-row {
  display: flex;
  gap: 1rem;
}

.id-input {
  flex: 1;
  max-width: 400px;
}

.result-summary {
  display: flex;
  gap: 2rem;
  margin-bottom: 1.5rem;
}

.summary-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1rem 2rem;
  border-radius: 10px;
  background: var(--panel);
  border: 1px solid var(--border);
}

.summary-item.success {
  border-color: #67c23a;
}

.summary-item.error {
  border-color: #f56c6c;
}

.summary-label {
  font-size: 0.85rem;
  color: var(--muted);
  margin-bottom: 0.3rem;
}

.summary-value {
  font-size: 2rem;
  font-weight: 700;
}

.result-tabs {
  height: calc(100% - 120px);
}

.validate-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}

.error-details {
  max-height: 400px;
  overflow-y: auto;
}

.error-item {
  padding: 0.75rem;
  margin-bottom: 0.5rem;
  background: #fdecec;
  border-radius: 6px;
  color: #f56c6c;
  font-family: monospace;
  font-size: 0.85rem;
  white-space: pre-wrap;
}
</style>
