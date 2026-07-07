<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'

const props = defineProps({
  record: {
    type: Object,
    default: null,
  },
})
const emit = defineEmits(['close'])

const formatted = computed(() => JSON.stringify(props.record, null, 2))

function onKeydown(event) {
  if (event.key === 'Escape') emit('close')
}

async function copyJson() {
  await navigator.clipboard.writeText(formatted.value)
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="record" class="drawer-layer" @click.self="emit('close')">
        <aside class="detail-drawer" aria-modal="true" role="dialog" aria-label="数据详情">
          <header>
            <div>
              <p class="eyebrow">RAW RECORD</p>
              <h2>记录 #{{ record.id }}</h2>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">×</button>
          </header>
          <div class="drawer-actions">
            <span>完整 JSON 数据</span>
            <button type="button" @click="copyJson">复制 JSON</button>
          </div>
          <pre>{{ formatted }}</pre>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>
