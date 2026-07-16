<script setup lang="ts">
import { ref } from 'vue'
import type { ControlAction, SystemMode } from '@/types/arm'

defineProps<{
  mode: SystemMode
  estop: boolean
}>()

const emit = defineEmits<{ action: [ControlAction] }>()
const pending = ref(false)

async function run(action: ControlAction) {
  if (pending.value) return
  pending.value = true
  try {
    emit('action', action)
  } finally {
    window.setTimeout(() => {
      pending.value = false
    }, 250)
  }
}
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <span>MODULE RUN GATE</span>
      <span>MODE={{ mode.toUpperCase() }}</span>
    </div>
    <div class="panel-body">
      <p class="comment">gates SC171V2 motion session · observation console only</p>
      <div class="grid">
        <button class="btn primary" :disabled="estop || pending" @click="run('start')">启动 START</button>
        <button class="btn" :disabled="pending" @click="run('pause')">暂停 PAUSE</button>
        <button class="btn danger" :disabled="pending" @click="run('estop')">急停 E-STOP</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
