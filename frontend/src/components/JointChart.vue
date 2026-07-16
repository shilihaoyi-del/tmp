<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { JOINT_LABELS } from '@/types/arm'

const props = defineProps<{ series: number[][] }>()
const canvas = ref<HTMLCanvasElement | null>(null)
let raf = 0

const COLORS = ['#e8e8e8', '#3dff6a', '#8a8a8a', '#ffb020', '#66a3ff', '#ff3b3b']

function draw() {
  const el = canvas.value
  if (!el) return
  const ctx = el.getContext('2d')
  if (!ctx) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const w = el.clientWidth
  const h = el.clientHeight
  el.width = Math.floor(w * dpr)
  el.height = Math.floor(h * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.lineWidth = 1
  for (let i = 0; i < 5; i++) {
    const y = (h / 4) * i
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
  }

  const mid = h / 2
  props.series.forEach((arr, idx) => {
    if (!arr.length) return
    ctx.beginPath()
    ctx.strokeStyle = COLORS[idx]
    ctx.lineWidth = idx === 1 ? 1.5 : 1
    arr.forEach((v, i) => {
      const x = (i / Math.max(arr.length - 1, 1)) * w
      const y = mid - (v / 180) * (h * 0.42)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()
  })
}

function loop() {
  draw()
  raf = requestAnimationFrame(loop)
}

onMounted(() => {
  raf = requestAnimationFrame(loop)
})
onUnmounted(() => cancelAnimationFrame(raf))
watch(() => props.series, draw, { deep: true })
</script>

<template>
  <div class="panel chart">
    <div class="panel-header">
      <span>JOINT ANGLE STREAM</span>
      <div class="legend">
        <span v-for="(label, i) in JOINT_LABELS" :key="label" :style="{ color: COLORS[i] }">
          {{ label.split('_')[0] }}
        </span>
      </div>
    </div>
    <div class="panel-body">
      <canvas ref="canvas" />
    </div>
  </div>
</template>

<style scoped>
.chart .panel-body {
  padding: 0;
}

canvas {
  width: 100%;
  height: 180px;
  display: block;
}

.legend {
  display: flex;
  gap: 10px;
  font-size: 10px;
  letter-spacing: 0.04em;
}
</style>
