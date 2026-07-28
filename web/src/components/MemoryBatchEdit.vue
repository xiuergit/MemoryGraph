<template>
  <div class="batch-edit-container">
    <div class="filter-section">
      <h3>筛选条件</h3>
      <div class="filter-row">
        <el-date-picker
          v-model="dateFrom"
          type="date"
          placeholder="起始日期"
          class="date-picker"
          value-format="YYYY-MM-DD"
        />
        <span class="date-separator">至</span>
        <el-date-picker
          v-model="dateTo"
          type="date"
          placeholder="结束日期"
          class="date-picker"
          value-format="YYYY-MM-DD"
        />
      </div>
      <el-select
        v-model="oldLocation"
        placeholder="原地址（可选）"
        clearable
        class="location-select"
        filterable
      >
        <el-option value="__EMPTY__" label="(空地址)" />
        <el-option
          v-for="item in locationItems"
          :key="item.location"
          :label="item.location"
          :value="item.location"
        />
      </el-select>
      <el-button type="primary" @click="previewPhotos">预览</el-button>
    </div>

    <div class="preview-section" v-if="previewPhotosList.length > 0">
      <h3>
        预览待修改照片（共 {{ previewPhotosList.length }} 张）
        <el-button type="info" size="small" @click="previewPhotosList = []">关闭预览</el-button>
      </h3>
      <el-table :data="previewPhotosList" max-height="300">
        <el-table-column label="photo_id" prop="photo_id" min-width="150" />
        <el-table-column label="时间" prop="timestamp" min-width="160" />
        <el-table-column label="原地址" prop="location" min-width="120" />
        <el-table-column label="省" prop="location_province" min-width="80" />
        <el-table-column label="市" prop="location_city" min-width="80" />
        <el-table-column label="区" prop="location_district" min-width="80" />
        <el-table-column label="操作" width="80">
          <template #default="scope">
            <el-button size="small" @click="$emit('view-detail', scope.row.photo_id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="update-section" v-if="previewPhotosList.length > 0">
      <h3>新地址信息</h3>
      <el-select
        v-model="newLocation"
        filterable
        allow-create
        default-first-option
        clearable
        placeholder="新地址名称（如：大润发）"
        class="location-input"
        @change="onNewLocationChange"
      >
        <el-option
          v-for="item in locationItems"
          :key="item.location"
          :label="item.location"
          :value="item.location"
        />
      </el-select>
      <div class="admin-row">
        <el-input
          v-model="province"
          placeholder="省（如：山西省）"
          class="admin-input"
        />
        <el-input
          v-model="city"
          placeholder="市（如：忻州市）"
          class="admin-input"
        />
        <el-input
          v-model="district"
          placeholder="区（如：忻府区）"
          class="admin-input"
        />
      </div>
      <el-input
        v-model="formattedAddress"
        placeholder="详细地址（如：山西省忻州市忻府区九原街街道慕山北路）"
        class="location-input"
      />
      <el-button
        type="danger"
        :loading="updating"
        @click="confirmUpdate"
      >
        确认修改（{{ previewPhotosList.length }} 条）
      </el-button>
    </div>

    <div class="result-section" v-if="updateResult">
      <el-alert
        :type="updateResult.success ? 'success' : 'warning'"
        :title="updateResult.message"
        show-icon
      />
      <div v-if="updateResult.failed && updateResult.failed.length > 0">
        <h4>失败记录：</h4>
        <ul>
          <li v-for="(error, index) in updateResult.failed" :key="index">{{ error }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

defineEmits(['view-detail'])

const dateFrom = ref('')
const dateTo = ref('')
const oldLocation = ref('')
const locations = ref([])
const locationItems = ref([])
const previewPhotosList = ref([])
const newLocation = ref('')
const province = ref('')
const city = ref('')
const district = ref('')
const formattedAddress = ref('')
const updating = ref(false)
const updateResult = ref(null)

async function loadLocations() {
  try {
    const res = await axios.get('/api/memory/locations')
    locations.value = res.data.locations || []
    locationItems.value = res.data.items || []
  } catch (error) {
    console.error('加载地址列表失败:', error)
    locations.value = []
    locationItems.value = []
  }
}

function onNewLocationChange(loc) {
  const item = locationItems.value.find((entry) => entry.location === loc)
  if (!item) {
    return
  }
  province.value = item.province || ''
  city.value = item.city || ''
  district.value = item.district || ''
  formattedAddress.value = item.formatted_address || item.location || ''
}

async function previewPhotos() {
  if (!dateFrom.value && !dateTo.value && !oldLocation.value) {
    alert('请至少选择一个筛选条件')
    return
  }
  const params = {
    page_size: 1000
  }
  if (dateFrom.value) params.date_from = dateFrom.value
  if (dateTo.value) params.date_to = dateTo.value
  if (oldLocation.value) params.location = oldLocation.value
  try {
    const res = await axios.get('/api/memory/list', { params })
    previewPhotosList.value = res.data.items
    updateResult.value = null
  } catch (error) {
    console.error('预览失败:', error)
    alert('预览失败')
  }
}

async function confirmUpdate() {
  if (!newLocation.value.trim()) {
    alert('新地址不能为空')
    return
  }
  if (!confirm(`确认修改 ${previewPhotosList.value.length} 条记录的地址？`)) {
    return
  }
  updating.value = true
  updateResult.value = null
  try {
    const res = await axios.post('/api/memory/batch-update-location', {
      date_from: dateFrom.value,
      date_to: dateTo.value,
      old_location: oldLocation.value,
      new_location: newLocation.value,
      province: province.value,
      city: city.value,
      district: district.value,
      formatted_address: formattedAddress.value,
    })
    updateResult.value = {
      success: true,
      ...res.data,
    }
    previewPhotosList.value = []
  } catch (error) {
    updateResult.value = {
      success: false,
      message: error.response?.data?.detail || '修改失败',
      failed: [],
    }
  } finally {
    updating.value = false
  }
}

onMounted(loadLocations)
</script>

<style scoped>
.batch-edit-container {
  height: 100%;
  min-height: 0;
  max-width: 800px;
  margin: 0 auto;
  overflow-x: hidden;
  overflow-y: auto;
  padding-bottom: 24px;
}

.filter-section,
.preview-section,
.update-section,
.result-section {
  margin-bottom: 24px;
  padding: 20px;
  background: var(--panel);
  border-radius: 8px;
  border: 1px solid var(--border);
}

.filter-section h3,
.preview-section h3,
.update-section h3 {
  margin: 0 0 16px;
  font-size: 16px;
  font-weight: 600;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.date-picker {
  width: 180px;
}

.date-separator {
  color: var(--muted);
}

.location-select {
  width: 100%;
  margin-bottom: 16px;
}

.location-input {
  width: 100%;
  margin-bottom: 16px;
}

.admin-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.admin-input {
  flex: 1;
}

.result-section {
  background: transparent;
  border: none;
  padding: 0;
}
</style>
