<script setup lang="ts">
import { JOINT_LABELS } from '@/types/arm'

defineProps<{
  target: number[]
  actual: number[]
}>()

function fmt(n: number) {
  const v = Number.isFinite(n) ? n : 0
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}°`
}
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <span>JOINT TELEMETRY</span>
      <span>TARGET / ACTUAL</span>
    </div>
    <div class="panel-body rows">
      <div v-for="(label, i) in JOINT_LABELS" :key="label" class="row">
        <div class="id">{{ label }}</div>
        <div class="bars">
          <div class="track">
            <div
              class="fill target"
              :style="{ width: Math.min(100, Math.abs(target[i] ?? 0) / 1.8) + '%' }"
            />
          </div>
          <div class="track">
            <div
              class="fill actual"
              :style="{ width: Math.min(100, Math.abs(actual[i] ?? 0) / 1.8) + '%' }"
            />
          </div>
        </div>
        <div class="vals">
          <span>{{ fmt(target[i] ?? 0) }}</span>
          <span class="dim">{{ fmt(actual[i] ?? 0) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rows {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.row {
  display: grid;
  grid-template-columns: 110px 1fr 92px;
  gap: 12px;
  align-items: center;
}

.id {
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-dim);
}

.bars {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.track {
  height: 2px;
  background: #1a1a1a;
  border: 1px solid var(--line);
}

.fill {
  height: 100%;
}

.fill.target {
  background: rgba(255, 255, 255, 0.55);
}

.fill.actual {
  background: var(--accent);
}

.vals {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-size: 11px;
}

.dim {
  display: block;
  color: var(--text-dim);
}
</style>
