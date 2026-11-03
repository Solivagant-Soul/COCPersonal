<template>
  <div class="stat-grid">
    <div v-for="item in items" :key="item.label" class="stat-grid__cell">
      <div class="stat-grid__label">{{ item.label }}</div>
      <div class="stat-grid__value" :class="{ 'stat-grid__value--text': item.icon }">
        <!-- 联赛这类带图标的格子：图标缺了就不占位，文字照常显示 -->
        <img
          v-if="item.icon"
          class="stat-grid__icon"
          :src="item.icon"
          :alt="item.iconAlt ?? item.label"
          loading="lazy"
          decoding="async"
        />
        <span>{{ item.value }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { StatItem } from './statItem'

defineProps<{ items: StatItem[] }>()
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  margin: 16px 0;
}
.stat-grid__cell {
  /* 详情页已经是大面板了：格子用浅一档底色，否则和面板同色只剩一圈边框 */
  background: var(--surface-subtle);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 12px;
}
.stat-grid__label {
  color: var(--text-secondary);
  font-size: 0.8125rem;
}
.stat-grid__value {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 1.375rem;
  font-weight: 600;
  margin-top: 4px;
  color: var(--text-primary);
}
.stat-grid__icon {
  /* 联赛徽章要看得出是哪一段：24px 太小，与数值同高才像「图标 + 名字」 */
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  object-fit: contain;
}
/* 带图标的格子装的是名字（如「传奇联赛」）不是数字：按字号 1.375rem 会被挤成两行 */
.stat-grid__value--text {
  font-size: 1rem;
  line-height: 1.5;
}
</style>
