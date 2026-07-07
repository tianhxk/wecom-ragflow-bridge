<script setup>
defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  loading: Boolean,
  hasQueried: Boolean,
})

const emit = defineEmits(['view', 'download'])

function formatSize(bytes) {
  if (!Number.isFinite(bytes)) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
}

function formatTime(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="table-shell log-browser">
    <div v-if="loading" class="table-loading">
      <span></span><span></span><span></span>
    </div>

    <div v-else-if="!hasQueried" class="empty-state">
      <div class="empty-illustration">≡</div>
      <h3>等待加载日志</h3>
      <p>输入访问令牌后，点击“浏览日志”。</p>
    </div>

    <div v-else-if="!items.length" class="empty-state">
      <div class="empty-illustration muted">0</div>
      <h3>暂时没有日志文件</h3>
      <p>请确认后端服务已启动并成功写入日志。</p>
    </div>

    <div v-else class="log-file-list">
      <article v-for="item in items" :key="item.name" class="log-file-card">
        <div class="log-file-icon">LOG</div>
        <div class="log-file-info">
          <div class="log-file-name">
            <strong>{{ item.name }}</strong>
            <span v-if="item.current">当前</span>
          </div>
          <p>{{ formatSize(item.size) }} · 更新于 {{ formatTime(item.modified_at) }}</p>
        </div>
        <div class="log-file-actions">
          <button type="button" @click="emit('view', item)">浏览</button>
          <button type="button" @click="emit('download', item)">下载</button>
        </div>
      </article>
    </div>
  </div>
</template>
