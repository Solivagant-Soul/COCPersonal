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
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 12px;
}
.stat-grid__label {
  color: var(--text-secondary);
  font-size: 0.8125rem;
}
.stat-grid__value {
  font-size: 1.375rem;
  font-weight: 600;
  margin-top: 4px;
  color: var(--text-primary);
}
</style>
