<template>
  <div class="knowledge">
    <aside class="side">
      <div class="side-scroll">
        <section v-for="group in groups" :key="group.id" class="group">
          <div class="group-label">{{ group.label }}</div>
          <button
            v-for="file in group.files"
            :key="file.path"
            type="button"
            class="file"
            :class="{ active: file.path === currentPath }"
            :title="file.path"
            @click="openFile(file.path)"
          >
            <span class="file-title">{{ file.title }}</span>
            <small v-if="showFileName(file)">{{ file.name }}</small>
          </button>
          <div v-if="!group.files.length" class="group-empty">暂无文件</div>
        </section>
      </div>
      <div class="side-foot">
        <el-button class="new-btn" @click="openCreate">新建学习笔记</el-button>
      </div>
    </aside>

    <section class="reader" v-loading="loading">
      <div v-if="currentPath" class="toolbar">
        <span class="path" :title="currentPath">{{ currentPath }}</span>
        <span v-if="dirty" class="dirty">未保存</span>
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="read">阅读</el-radio-button>
          <el-radio-button value="edit">编辑</el-radio-button>
        </el-radio-group>
        <el-button type="primary" size="small" :disabled="!dirty" :loading="saving" @click="save">
          保存
        </el-button>
      </div>

      <div
        v-if="currentPath && mode === 'read'"
        class="preview markdown"
        v-html="html"
        @click="onPreviewClick"
      />
      <textarea
        v-else-if="currentPath"
        v-model="draft"
        class="editor"
        spellcheck="false"
        @keydown="onEditorKeydown"
      />
      <el-empty v-else description="从左侧选择一篇文档" />
    </section>

    <el-dialog v-model="createVisible" title="新建学习笔记" width="420px" @closed="createName = ''">
      <p class="create-hint">写在 docs/ai-study/ 里，和现有学习笔记放在一起。</p>
      <el-input
        v-model="createName"
        placeholder="笔记名，例如 W11 记录"
        maxlength="80"
        @keydown.enter="createNote"
      />
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createNote">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ gfm: true, breaks: false })

const groups = ref([])
const currentPath = ref('')
const saved = ref('')
const draft = ref('')
const mode = ref('read')
const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const createVisible = ref(false)
const createName = ref('')

const dirty = computed(() => currentPath.value !== '' && draft.value !== saved.value)
const html = computed(() => {
  if (!draft.value) return ''
  return DOMPurify.sanitize(marked.parse(draft.value))
})

function showFileName(file) {
  const stem = file.name.replace(/\.md$/i, '')
  return file.title !== stem && file.title !== file.name
}

function errorDetail(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

async function loadGroups() {
  const res = await axios.get('/api/docs')
  groups.value = res.data.groups || []
}

async function openFile(path) {
  if (!path || path === currentPath.value) return
  if (!(await confirmLeave())) return
  loading.value = true
  try {
    const res = await axios.get('/api/docs/file', { params: { path } })
    currentPath.value = res.data.path
    saved.value = res.data.content || ''
    draft.value = saved.value
    mode.value = 'read'
  } catch (error) {
    ElMessage.error(errorDetail(error, '打不开这篇文档'))
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!currentPath.value || !dirty.value || saving.value) return
  saving.value = true
  try {
    await axios.put('/api/docs/file', {
      path: currentPath.value,
      content: draft.value,
    })
    saved.value = draft.value
    ElMessage.success('已写回文件')
    await loadGroups()
  } catch (error) {
    ElMessage.error(errorDetail(error, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function confirmLeave() {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('这篇还有没保存的修改。', '未保存', {
      confirmButtonText: '不保存并离开',
      cancelButtonText: '回去保存',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
}

function openCreate() {
  createName.value = ''
  createVisible.value = true
}

async function createNote() {
  const name = createName.value.trim()
  if (!name || creating.value) return
  if (!(await confirmLeave())) return
  creating.value = true
  try {
    const res = await axios.post('/api/docs/file', { name })
    createVisible.value = false
    await loadGroups()
    currentPath.value = res.data.path
    saved.value = res.data.content || ''
    draft.value = saved.value
    mode.value = 'edit'
    ElMessage.success('已新建笔记')
  } catch (error) {
    ElMessage.error(errorDetail(error, '创建失败'))
  } finally {
    creating.value = false
  }
}

function resolveDocHref(href) {
  const clean = href.split('#')[0].split('?')[0].trim()
  if (!clean || /^(https?:|mailto:)/i.test(clean)) return null
  const base = currentPath.value.split('/').slice(0, -1)
  const stack = []
  for (const part of base.concat(clean.split('/'))) {
    if (!part || part === '.') continue
    if (part === '..') {
      stack.pop()
      continue
    }
    try {
      stack.push(decodeURIComponent(part))
    } catch {
      stack.push(part)
    }
  }
  const path = stack.join('/')
  if (!path.startsWith('docs/') || !path.toLowerCase().endsWith('.md')) return null
  return path
}

function onPreviewClick(event) {
  const link = event.target.closest('a')
  if (!link) return
  const href = link.getAttribute('href') || ''
  if (/^https?:/i.test(href)) {
    event.preventDefault()
    window.open(href, '_blank', 'noopener')
    return
  }
  const path = resolveDocHref(href)
  if (!path) return
  event.preventDefault()
  openFile(path)
}

function onEditorKeydown(event) {
  if ((event.metaKey || event.ctrlKey) && event.key === 's') {
    event.preventDefault()
    save()
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await loadGroups()
    const first = groups.value.flatMap((group) => group.files)[0]
    if (first) await openFile(first.path)
  } catch (error) {
    ElMessage.error(errorDetail(error, '文档列表加载失败'))
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.knowledge {
  height: 100%;
  min-height: 0;
  display: flex;
  gap: 12px;
}

.side {
  width: 260px;
  flex-shrink: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
}

.side-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px;
}

.group + .group {
  margin-top: 12px;
}

.group-label {
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.group-empty {
  padding: 4px 8px 8px;
  font-size: 12px;
  color: var(--muted);
}

.file {
  display: block;
  width: 100%;
  margin: 0;
  padding: 6px 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  color: var(--text);
}

.file:hover {
  background: var(--table-hover);
}

.file.active {
  background: var(--table-current);
  color: var(--text-strong);
}

.file-title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.file small {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-foot {
  flex-shrink: 0;
  padding: 8px;
  border-top: 1px solid var(--border);
}

.new-btn {
  width: 100%;
}

.reader {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
  overflow: hidden;
}

.toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}

.path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.dirty {
  flex-shrink: 0;
  color: #b26a00;
  font-size: 12px;
}

.preview {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px 20px 40px;
}

.editor {
  flex: 1;
  min-height: 0;
  width: 100%;
  margin: 0;
  padding: 16px 20px 40px;
  border: none;
  resize: none;
  outline: none;
  background: var(--panel);
  color: var(--text-strong);
  font: 14px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
}

.create-hint {
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 13px;
}

.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3) {
  color: var(--text-strong);
  line-height: 1.3;
}

.markdown :deep(h1) {
  font-size: 1.45rem;
  margin: 0.6rem 0 0.8rem;
}

.markdown :deep(h2) {
  font-size: 1.15rem;
  margin: 1.4rem 0 0.6rem;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid var(--border);
}

.markdown :deep(h3) {
  font-size: 1rem;
  margin: 1.1rem 0 0.4rem;
}

.markdown :deep(p),
.markdown :deep(li) {
  line-height: 1.65;
}

.markdown :deep(a) {
  color: var(--accent);
}

.markdown :deep(code) {
  padding: 0.1em 0.35em;
  border-radius: 4px;
  background: var(--panel-2);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.92em;
}

.markdown :deep(pre) {
  overflow: auto;
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--panel-2);
}

.markdown :deep(pre code) {
  padding: 0;
  background: transparent;
}

.markdown :deep(blockquote) {
  margin: 0.8rem 0;
  padding: 0.2rem 0 0.2rem 0.9rem;
  border-left: 3px solid var(--border);
  color: var(--muted);
}

.markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.8rem 0 1rem;
  font-size: 13px;
}

.markdown :deep(th),
.markdown :deep(td) {
  padding: 6px 8px;
  border: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}

.markdown :deep(th) {
  background: var(--table-header);
  color: var(--text-strong);
}
</style>
