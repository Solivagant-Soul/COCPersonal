<template>
  <div class="stat-grid">
    <div v-for="item in items" :key="item.label" class="stat-grid__cell">
      <div class="stat-grid__label">{{ item.label }}</div>
      <div class="stat-grid__value">{{ item.value }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ items: Array<{ label: string; value: string }> }>()
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  margin: 16px 0;
}
.stat-grid__cell {
  background: #fff;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
}
.stat-grid__label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.stat-grid__value {
  font-size: 20px;
  font-weight: 600;
  margin-top: 4px;
}
</style>
