<script setup>
defineProps({
  source: {
    type: String,
    required: true,
  },
  items: {
    type: Array,
    default: () => [],
  },
  loading: Boolean,
  hasQueried: Boolean,
})

const emit = defineEmits(['view'])

function formatTime(value) {
  if (!value) return '—'
  const normalized = /Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function statusLabel(status) {
  return {
    pending: '待处理',
    processing: '处理中',
    done: '已完成',
    failed: '失败',
    skipped: '已跳过',
  }[status] || status || '未知'
}
</script>

<template>
  <div class="table-shell">
    <div v-if="loading" class="table-loading">
      <span></span><span></span><span></span>
    </div>

    <div v-if="!hasQueried && !loading" class="empty-state">
      <div class="empty-illustration">⌕</div>
      <h3>等待第一次查询</h3>
      <p>填写左侧条件后，结果会在这里展开。</p>
    </div>

    <div v-else-if="!items.length && !loading" class="empty-state">
      <div class="empty-illustration muted">0</div>
      <h3>没有匹配的数据</h3>
      <p>可以调整时间范围或筛选条件后重试。</p>
    </div>

    <div v-else class="table-scroll">
      <table v-if="source === 'messages'">
        <thead>
          <tr>
            <th>ID</th>
            <th>消息时间</th>
            <th>会话 / 发送人</th>
            <th>类型</th>
            <th class="content-column">消息内容</th>
            <th>状态</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td class="mono">#{{ item.id }}</td>
            <td class="nowrap">{{ formatTime(item.messagetime) }}</td>
            <td>
              <strong>{{ item.groupname || '—' }}</strong>
              <small>{{ item.groupnickname || item.corpsName || '未知发送人' }}</small>
            </td>
            <td>
              <span class="type-chip">{{ item.messagetype || item.mode || '—' }}</span>
            </td>
            <td class="message-cell" :title="item.message || ''">{{ item.message || '—' }}</td>
            <td>
              <span class="status-chip" :class="`status-${item.process_status}`">
                {{ statusLabel(item.process_status) }}
              </span>
            </td>
            <td>
              <button class="detail-button" type="button" @click="emit('view', item)">详情</button>
            </td>
          </tr>
        </tbody>
      </table>

      <table v-else>
        <thead>
          <tr>
            <th>ID</th>
            <th>接收时间</th>
            <th>机器人 ID</th>
            <th>模式</th>
            <th class="content-column">回调摘要</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td class="mono">#{{ item.id }}</td>
            <td class="nowrap">{{ formatTime(item.received_at) }}</td>
            <td class="mono">{{ item.robotid }}</td>
            <td><span class="type-chip">{{ item.mode || '—' }}</span></td>
            <td class="message-cell">{{ JSON.stringify(item.raw_json) }}</td>
            <td>
              <button class="detail-button" type="button" @click="emit('view', item)">详情</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
