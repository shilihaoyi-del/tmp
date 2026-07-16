<script setup lang="ts">
defineProps<{
  label: string
  value: string
  tone?: 'active' | 'warn' | 'danger' | ''
}>()
</script>

<template>
  <span class="sensor-tag" :class="tone">
    <i class="led" />
    <span>[{{ label }}: {{ value }}]</span>
  </span>
</template>
