<script setup>
import { computed, reactive, ref } from 'vue'

defineProps({
  loading: Boolean,
})

const emit = defineEmits(['search'])

const now = new Date()
const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000)
const toLocalInput = (date) => {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

const form = reactive({
  source: 'messages',
  token: sessionStorage.getItem('workbot_query_token') || '',
  robotid: '',
  start_time: toLocalInput(yesterday),
  end_time: toLocalInput(now),
  mode: '',
  messageid: '',
  groupname: '',
  groupnickname: '',
  messagetype: '',
  process_status: '',
  limit: '100',
})
const rememberToken = ref(Boolean(form.token))
const showAdvanced = ref(false)

const isMessages = computed(() => form.source === 'messages')
const isLogs = computed(() => form.source === 'logs')

function submit() {
  if (rememberToken.value) {
    sessionStorage.setItem('workbot_query_token', form.token)
  } else {
    sessionStorage.removeItem('workbot_query_token')
  }

  const query = {}
  if (!isLogs.value) {
    Object.assign(query, {
      robotid: form.robotid.trim(),
      start_time: new Date(form.start_time).toISOString(),
      end_time: new Date(form.end_time).toISOString(),
      mode: form.mode.trim(),
      limit: form.limit,
    })
  }
  if (isMessages.value) {
    Object.assign(query, {
      messageid: form.messageid.trim(),
      groupname: form.groupname.trim(),
      groupnickname: form.groupnickname.trim(),
      messagetype: form.messagetype.trim(),
      process_status: form.process_status,
    })
  }
  emit('search', {
    source: form.source,
    token: form.token.trim(),
    query,
  })
}
</script>

<template>
  <form class="query-panel" @submit.prevent="submit">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">QUERY BUILDER</p>
        <h2>查询条件</h2>
      </div>
      <span class="required-note"><i></i> 标记为必填</span>
    </div>

    <div class="form-grid">
      <label class="field field-wide">
        <span>访问令牌 <b>*</b></span>
        <input
          v-model="form.token"
          type="password"
          autocomplete="current-password"
          placeholder="WORKBOT_QUERY_API_TOKEN"
          required
        />
        <small>
          <label class="check-label">
            <input v-model="rememberToken" type="checkbox" />
            仅在当前浏览器会话中记住
          </label>
        </small>
      </label>

      <label class="field">
        <span>数据来源 <b>*</b></span>
        <select v-model="form.source">
          <option value="messages">消息记录 message</option>
          <option value="callback-logs">回调日志 callback_log</option>
          <option value="logs">服务日志 logs</option>
        </select>
      </label>

      <template v-if="!isLogs">
        <label class="field">
          <span>机器人 ID <b>*</b></span>
          <input v-model="form.robotid" placeholder="robot_id_1" required />
        </label>

        <label class="field">
          <span>开始时间 <b>*</b></span>
          <input v-model="form.start_time" type="datetime-local" required />
        </label>

        <label class="field">
          <span>结束时间 <b>*</b></span>
          <input v-model="form.end_time" type="datetime-local" required />
        </label>

        <label class="field">
          <span>回调模式</span>
          <input v-model="form.mode" placeholder="例如 logs" />
        </label>

        <label class="field">
          <span>每页数量</span>
          <select v-model="form.limit">
            <option value="20">20 条</option>
            <option value="50">50 条</option>
            <option value="100">100 条</option>
            <option value="200">200 条</option>
          </select>
        </label>
      </template>
    </div>

    <template v-if="isMessages">
      <button class="advanced-toggle" type="button" @click="showAdvanced = !showAdvanced">
        <span>{{ showAdvanced ? '收起' : '展开' }}消息筛选</span>
        <span :class="{ rotated: showAdvanced }">⌄</span>
      </button>

      <div v-show="showAdvanced" class="form-grid advanced-fields">
        <label class="field">
          <span>处理状态</span>
          <select v-model="form.process_status">
            <option value="">全部状态</option>
            <option value="pending">待处理 pending</option>
            <option value="processing">处理中 processing</option>
            <option value="done">已完成 done</option>
            <option value="failed">失败 failed</option>
            <option value="skipped">已跳过 skipped</option>
          </select>
        </label>
        <label class="field">
          <span>消息类型</span>
          <input v-model="form.messagetype" placeholder="例如 text" />
        </label>
        <label class="field">
          <span>群聊名称</span>
          <input v-model="form.groupname" placeholder="精确匹配" />
        </label>
        <label class="field">
          <span>群内昵称</span>
          <input v-model="form.groupnickname" placeholder="精确匹配" />
        </label>
        <label class="field field-wide">
          <span>消息 ID</span>
          <input v-model="form.messageid" placeholder="完整 messageid" />
        </label>
      </div>
    </template>

    <div class="form-actions">
      <p v-if="isLogs">显示当前日志及最近 30 天的轮转文件。</p>
      <p v-else>时间会自动转换为 UTC，单次范围最多 31 天。</p>
      <button class="primary-button" type="submit" :disabled="loading">
        <span v-if="loading" class="spinner"></span>
        <span>{{ loading ? '加载中…' : (isLogs ? '浏览日志' : '开始查询') }}</span>
      </button>
    </div>
  </form>
</template>
