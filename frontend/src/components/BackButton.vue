<template>
  <button type="button" class="page-back" @click="goBack">← 返回</button>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

/**
 * 详情页左上角的独立返回按钮。
 *
 * 位置约定：**放在 `.page` 里、`.page-card` 之外**（见 `pages/PlayerDetail.vue`），
 * 而不是塞进卡片顶部 —— 卡片内那行小字会和标题抢视线，也容易被误当成面包屑。
 *
 * 直接打开详情页（没有上一页）时回查询页，别把用户甩出站点。
 */
const props = withDefaults(defineProps<{ fallback?: string }>(), { fallback: 'query' })

const router = useRouter()

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push({ name: props.fallback })
}
</script>

<style scoped>
.page-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 12px;
  padding: 6px 14px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-secondary);
  font-size: 0.875rem;
  line-height: 1.4;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.page-back:hover {
  color: var(--accent-gold);
  border-color: var(--accent-gold);
}
.page-back:focus-visible {
  outline: 2px solid var(--accent-gold);
  outline-offset: 2px;
}
</style>
