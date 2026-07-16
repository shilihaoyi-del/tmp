<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { ArmScene } from '@/lib/armScene'

const props = defineProps<{ angles: number[] }>()
const host = ref<HTMLElement | null>(null)
let scene: ArmScene | null = null

onMounted(() => {
  if (!host.value) return
  scene = new ArmScene(host.value)
  scene.setJoints(props.angles)
})

watch(
  () => [...props.angles],
  (v) => scene?.setJoints(v),
  { deep: true },
)

onUnmounted(() => {
  scene?.dispose()
  scene = null
})
</script>

<template>
  <div class="viewport panel">
    <div class="panel-header">
      <span>VIEWPORT // SC171V2 COMMAND EFFECT</span>
      <span class="hint">DRAG TO ORBIT</span>
    </div>
    <div ref="host" class="canvas-host" />
    <p class="comment footer">arm motion proves module command delivery · urdf kinematics preview</p>
  </div>
</template>

<style scoped>
.viewport {
  display: flex;
  flex-direction: column;
  min-height: 420px;
  height: 100%;
}

.hint {
  color: var(--text-faint);
}

.canvas-host {
  flex: 1;
  min-height: 360px;
  background:
    radial-gradient(ellipse at 50% 30%, rgba(61, 255, 106, 0.05), transparent 55%),
    #070707;
}

.footer {
  margin: 0;
  padding: 8px 14px 12px;
  border-top: 1px solid var(--line);
}
</style>
