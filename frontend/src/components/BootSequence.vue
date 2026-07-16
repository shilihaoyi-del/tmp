<script setup lang="ts">
import { onMounted, ref } from 'vue'
import gsap from 'gsap'

const props = defineProps<{ active: boolean }>()
const emit = defineEmits<{ done: [] }>()

const percent = ref(0)
const line = ref('LINK RADIO...')
const lines = [
  'LINK RADIO 5G / Wi-Fi...',
  'OPEN MQTT SESSION',
  'EDGE SAFETY CHECK',
  'SUBSCRIBE arm/device/cmd',
  'HEARTBEAT WATCHDOG',
  'SC171V2 READY',
]

onMounted(() => {
  if (!props.active) {
    emit('done')
    return
  }
  const state = { p: 0 }
  gsap.to(state, {
    p: 100,
    duration: 2.4,
    ease: 'none',
    onUpdate: () => {
      percent.value = Math.floor(state.p)
      const idx = Math.min(lines.length - 1, Math.floor((state.p / 100) * lines.length))
      line.value = lines[idx]
    },
    onComplete: () => {
      gsap.to('.boot', {
        opacity: 0,
        duration: 0.45,
        ease: 'power1.in',
        onComplete: () => emit('done'),
      })
    },
  })
})
</script>

<template>
  <div class="boot">
    <div class="boot-inner">
      <div class="brand">FIBOCOM <span>SC171V2</span></div>
      <p class="comment">5G smart module power-on · edge control plane self-check</p>
      <div class="bar">
        <div class="fill" :style="{ width: percent + '%' }" />
      </div>
      <div class="meta">
        <span>[BOOT {{ String(percent).padStart(3, '0') }}%]</span>
        <span>{{ line }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.boot {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: #000;
  display: grid;
  place-items: center;
}

.boot-inner {
  width: min(560px, 88vw);
}

.brand {
  font-family: var(--display);
  font-size: clamp(28px, 7vw, 48px);
  font-weight: 600;
  letter-spacing: 0.08em;
}

.brand span {
  color: var(--accent);
}

.bar {
  margin-top: 28px;
  height: 2px;
  background: #1a1a1a;
  border: 1px solid var(--line);
}

.fill {
  height: 100%;
  background: var(--accent);
  width: 0%;
}

.meta {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  color: var(--text-dim);
  font-size: 11px;
  letter-spacing: 0.06em;
}
</style>
