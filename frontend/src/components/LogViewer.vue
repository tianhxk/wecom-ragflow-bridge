<script setup>
import { onBeforeUnmount, onMounted } from 'vue'

defineProps({
  preview: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['close', 'download'])

function onKeydown(event) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="preview" class="drawer-layer" @click.self="emit('close')">
        <aside class="detail-drawer log-drawer" aria-modal="true" role="dialog" aria-label="日志内容">
          <header>
            <div>
              <p class="eyebrow">LOG PREVIEW</p>
              <h2>{{ preview.filename }}</h2>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
          </header>

          <div class="drawer-actions">
            <span v-if="preview.truncated">仅显示文件末尾内容</span>
            <span v-else>完整内容</span>
            <button type="button" :disabled="preview.loading" @click="emit('download', preview)">
              下载原文件
            </button>
          </div>

          <div v-if="preview.loading" class="log-preview-state">正在读取日志…</div>
          <div v-else-if="preview.error" class="log-preview-state error">{{ preview.error }}</div>
          <pre v-else>{{ preview.content || '日志文件为空' }}</pre>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>
