<script setup>
import { computed, ref } from 'vue'
import DataTable from './components/DataTable.vue'
import DetailDrawer from './components/DetailDrawer.vue'
import LogBrowser from './components/LogBrowser.vue'
import LogViewer from './components/LogViewer.vue'
import QueryForm from './components/QueryForm.vue'
import { downloadLogFile, queryLogFiles, queryRecords, readLogFile } from './services/workbotApi'

const appVersion = import.meta.env.VITE_APP_VERSION || '1.0'

const loading = ref(false)
const error = ref('')
const records = ref([])
const source = ref('messages')
const nextBeforeId = ref(null)
const hasQueried = ref(false)
const currentPage = ref(0)
const lastRequest = ref(null)
const selectedRecord = ref(null)
const logPreview = ref(null)
const queriedAt = ref('')

const sourceLabel = computed(() => ({
  messages: 'message',
  'callback-logs': 'callback_log',
  logs: '服务日志',
})[source.value])

async function search(payload) {
  source.value = payload.source
  currentPage.value = 1
  lastRequest.value = payload
  records.value = []
  nextBeforeId.value = null
  hasQueried.value = false
  selectedRecord.value = null
  logPreview.value = null
  if (payload.source === 'logs') {
    currentPage.value = 0
    await executeLogs(payload)
  } else {
    await execute(payload, false)
  }
}

async function executeLogs(payload) {
  loading.value = true
  error.value = ''
  try {
    const data = await queryLogFiles(payload.token)
    records.value = data.items
    queriedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    hasQueried.value = true
  } catch (err) {
    error.value = err.message || '读取日志列表失败'
  } finally {
    loading.value = false
  }
}

async function nextPage() {
  if (!lastRequest.value || !nextBeforeId.value) return
  currentPage.value += 1
  await execute({
    ...lastRequest.value,
    query: {
      ...lastRequest.value.query,
      before_id: nextBeforeId.value,
    },
  }, true)
}

async function execute(payload, isPaging) {
  loading.value = true
  error.value = ''
  try {
    const data = await queryRecords(payload.source, payload.token, payload.query)
    records.value = data.items
    nextBeforeId.value = data.next_before_id
    queriedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    hasQueried.value = true
  } catch (err) {
    error.value = err.message || '查询失败'
    if (isPaging) currentPage.value -= 1
  } finally {
    loading.value = false
  }
}

function exportJson() {
  const blob = new Blob([JSON.stringify(records.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${sourceLabel.value}-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  link.click()
  URL.revokeObjectURL(url)
}

async function viewLog(item) {
  logPreview.value = {
    filename: item.name,
    content: '',
    truncated: false,
    loading: true,
    error: '',
  }
  try {
    const data = await readLogFile(item.name, lastRequest.value.token, 1000)
    logPreview.value = { ...data, loading: false, error: '' }
  } catch (err) {
    logPreview.value = {
      ...logPreview.value,
      loading: false,
      error: err.message || '读取日志失败',
    }
  }
}

async function downloadLog(item) {
  const filename = item.name || item.filename
  try {
    await downloadLogFile(filename, lastRequest.value.token)
  } catch (err) {
    error.value = err.message || '下载日志失败'
  }
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="/">
        <span class="brand-mark">W</span>
        <span>
          <strong>WorkBot</strong>
          <small>数据查询台</small>
        </span>
      </a>
      <div class="service-state">
        <span></span>
        只读查询服务
      </div>
    </header>

    <main>
      <section class="hero">
        <div>
          <p class="eyebrow">MESSAGE INTELLIGENCE</p>
          <h1>找到每一次<br /><em>真实的对话</em></h1>
          <p class="hero-copy">
            查询 WorkBot 消息与原始回调，快速定位处理状态、上下文和异常记录。
          </p>
        </div>
        <div class="hero-meta">
          <div><strong>3</strong><span>数据源</span></div>
          <div><strong>200</strong><span>单页上限</span></div>
          <div><strong>31d</strong><span>最大跨度</span></div>
        </div>
      </section>

      <section class="workspace">
        <QueryForm :loading="loading" @search="search" />

        <div class="results-panel">
          <div class="results-header">
            <div>
              <p class="eyebrow">RESULTS</p>
              <h2>查询结果</h2>
            </div>
            <div class="result-actions">
              <button
                v-if="source !== 'logs'"
                type="button"
                :disabled="!records.length"
                @click="exportJson"
              >导出 JSON</button>
            </div>
          </div>

          <div v-if="error" class="error-banner">
            <span>!</span>
            <div><strong>查询没有完成</strong><p>{{ error }}</p></div>
            <button type="button" aria-label="关闭" @click="error = ''">×</button>
          </div>

          <div class="result-summary">
            <div><span>数据来源</span><strong>{{ sourceLabel }}</strong></div>
            <div><span>当前结果</span><strong>{{ records.length }} {{ source === 'logs' ? '个文件' : '条' }}</strong></div>
            <div><span>当前页</span><strong>{{ source === 'logs' ? '—' : `第 ${currentPage || '—'} 页` }}</strong></div>
            <div><span>更新时间</span><strong>{{ queriedAt || '尚未查询' }}</strong></div>
          </div>

          <LogBrowser
            v-if="source === 'logs'"
            :items="records"
            :loading="loading"
            :has-queried="hasQueried"
            @view="viewLog"
            @download="downloadLog"
          />

          <DataTable
            v-else
            :source="source"
            :items="records"
            :loading="loading"
            :has-queried="hasQueried"
            @view="selectedRecord = $event"
          />

          <div v-if="hasQueried && source !== 'logs'" class="pagination">
            <p>{{ nextBeforeId ? `下一页游标 #${nextBeforeId}` : '已经到达结果末尾' }}</p>
            <button type="button" :disabled="!nextBeforeId || loading" @click="nextPage">
              加载下一页 →
            </button>
          </div>
        </div>
      </section>
    </main>

    <footer>
      <span>WorkBot Query Console · v{{ appVersion }}</span>
      <span>所有查询均为只读 · Token 不写入 URL</span>
    </footer>

    <DetailDrawer :record="selectedRecord" @close="selectedRecord = null" />
    <LogViewer :preview="logPreview" @close="logPreview = null" @download="downloadLog" />
  </div>
</template>
