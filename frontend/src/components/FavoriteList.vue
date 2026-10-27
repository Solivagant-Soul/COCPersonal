<template>
  <div v-if="entries.length" class="favorites">
    <div class="favorites__head">
      <span class="favorites__title">我的关注</span>
      <button type="button" class="favorites__clear" @click="onClear">清空</button>
    </div>

    <ul class="favorites__list">
      <li v-for="entry in entries" :key="entry.kind + entry.tag" class="favorites__item">
        <router-link :to="routeFor(entry)" class="favorites__link">
          <span class="favorites__kind" :class="`favorites__kind--${entry.kind}`">
            {{ kindLabel(entry.kind) }}
          </span>
          <span class="favorites__name">{{ entry.name || entry.tag }}</span>
          <span v-if="entry.name" class="favorites__tag">{{ entry.tag }}</span>
        </router-link>
        <button
          type="button"
          class="favorites__remove"
          :aria-label="`取消关注 ${entry.tag}`"
          @click="onRemove(entry)"
        >
          ✕
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  clearFavorites,
  readFavorites,
  removeFavorite,
  type FavoriteEntry,
  type FavoriteKind,
} from '../utils/favorites'

/**
 * 查询页的「我的关注」区块。
 *
 * 与 `SearchHistory` 同构：没有关注时整块不渲染，卡片也就不会留一条孤零零的分隔线。
 * 数据源是 localStorage，详情页里点过「关注」之后回到本页，组件重新挂载即刷新。
 */
const entries = ref<FavoriteEntry[]>([])

function refresh() {
  entries.value = readFavorites()
}

onMounted(refresh)

function kindLabel(kind: FavoriteKind): string {
  return kind === 'clan' ? '部落' : '玩家'
}

function routeFor(entry: FavoriteEntry) {
  return {
    name: entry.kind === 'clan' ? 'clan' : 'player',
    params: { tag: entry.tag },
  }
}

function onRemove(entry: FavoriteEntry) {
  removeFavorite(entry.tag, entry.kind)
  refresh()
}

function onClear() {
  clearFavorites()
  refresh()
}
</script>

<style scoped>
.favorites {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--border-default);
}
.favorites__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.favorites__title {
  font-size: 0.9375rem;
  color: var(--text-secondary);
}
.favorites__clear {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 0.875rem;
  color: var(--text-secondary);
  padding: 0;
}
.favorites__clear:hover {
  color: var(--accent-gold);
}
.favorites__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.favorites__item {
  display: flex;
  align-items: center;
  background: var(--surface-subtle);
  border: 1px solid var(--border-default);
  border-radius: 999px;
  overflow: hidden;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.favorites__item:hover {
  border-color: var(--border-strong);
}
.favorites__link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 4px 6px 12px;
  color: var(--text-primary);
  text-decoration: none;
  font-size: 0.875rem;
  white-space: nowrap;
}
.favorites__link:hover {
  color: var(--accent-gold);
}
.favorites__kind {
  font-size: 0.75rem;
  padding: 0 6px;
  border-radius: 4px;
  line-height: 18px;
}
.favorites__kind--player {
  background: #e0a03026;
  color: var(--accent-gold);
}
.favorites__kind--clan {
  background: #3ad1c026;
  color: var(--tier-b);
}
/* 名字在前、标签在后；名字太长时截断，别把 chip 撑成一整行 */
.favorites__name {
  max-width: 12em;
  overflow: hidden;
  text-overflow: ellipsis;
}
.favorites__tag {
  color: var(--text-faint);
  font-size: 0.8125rem;
}
.favorites__remove {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--text-faint);
  padding: 6px 12px 6px 6px;
  font-size: 0.8125rem;
  line-height: 1;
}
.favorites__remove:hover {
  color: var(--accent-danger);
}
</style>
