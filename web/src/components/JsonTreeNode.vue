<template>
  <div class="json-node">
    <div v-if="isObject" class="object-node">
      <span class="node-key" @click="toggle">{{ key ? `"${key}": ` : '' }}</span>
      <span class="bracket" @click="toggle">{{ expanded ? '{' : '{' }}</span>
      <span v-if="!expanded && hasChildren" class="ellipsis"> ...</span>
      <span v-if="expanded" class="bracket-close">}</span>

      <div v-if="expanded && hasChildren" class="children">
        <JsonTreeNode
          v-for="(value, childKey) in data"
          :key="String(childKey)"
          :key-name="childKey"
          :data="value"
          :level="level + 1"
        />
      </div>
    </div>

    <div v-else-if="isArray" class="array-node">
      <span class="node-key" @click="toggle">{{ key ? `"${key}": ` : '' }}</span>
      <span class="bracket" @click="toggle">[</span>
      <span v-if="!expanded && data.length" class="ellipsis"> {{ data.length }} items...</span>
      <span v-if="expanded" class="bracket-close">]</span>

      <div v-if="expanded && data.length" class="children">
        <JsonTreeNode
          v-for="(value, index) in data"
          :key="index"
          :key-name="index"
          :data="value"
          :level="level + 1"
        />
      </div>
    </div>

    <div v-else class="leaf-node">
      <span class="node-key">{{ key ? `"${key}": ` : '' }}</span>
      <span :class="getValueClass(data)">{{ formatValue(data) }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  keyName: {
    type: [String, Number],
    default: null,
  },
  data: {
    type: [Object, Array, String, Number, Boolean, null],
    default: null,
  },
  level: {
    type: Number,
    default: 0,
  },
})

const expanded = ref(true)

const key = computed(() => props.keyName)
const isObject = computed(() => typeof props.data === 'object' && props.data !== null && !Array.isArray(props.data))
const isArray = computed(() => Array.isArray(props.data))
const hasChildren = computed(() => {
  if (isObject.value) return Object.keys(props.data).length > 0
  if (isArray.value) return props.data.length > 0
  return false
})

function toggle() {
  if (hasChildren.value) {
    expanded.value = !expanded.value
  }
}

function formatValue(value) {
  if (value === null) return 'null'
  if (typeof value === 'string') return `"${value}"`
  if (typeof value === 'boolean') return String(value)
  if (typeof value === 'number') return String(value)
  return String(value)
}

function getValueClass(value) {
  if (value === null) return 'null-value'
  if (typeof value === 'string') return 'string-value'
  if (typeof value === 'boolean') return 'boolean-value'
  if (typeof value === 'number') return 'number-value'
  return ''
}
</script>

<style scoped>
.json-node {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  padding: 2px 0;
}

.object-node,
.array-node {
  width: 100%;
}

.node-key {
  color: #c678dd;
  cursor: pointer;
  user-select: none;
}

.node-key:hover {
  text-decoration: underline;
}

.bracket {
  color: var(--text);
  cursor: pointer;
  user-select: none;
}

.bracket-close {
  color: var(--text);
}

.ellipsis {
  color: var(--muted);
}

.children {
  margin-left: 20px;
  padding-left: 10px;
  border-left: 1px solid var(--border);
}

.leaf-node {
  width: 100%;
}

.string-value {
  color: #98c379;
}

.number-value {
  color: #d19a66;
}

.boolean-value {
  color: #56b6c2;
}

.null-value {
  color: var(--muted);
}
</style>
