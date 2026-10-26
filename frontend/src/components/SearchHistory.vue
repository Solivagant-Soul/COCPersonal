<template>
  <div v-if="entries.length" class="history">
    <div class="history__head">
      <span class="history__title">最近查询</span>
      <button type="button" class="history__clear" @click="onClear">清空</button>
    </div>

    <ul class="history__list">
      <li v-for="entry in entries" :key="entry.kind + entry.tag" class="history__item">
        <router-link :to="routeFor(entry)" class="history__link">
          <span class="history__kind" :class="`history__kind--${entry.kind}`">
            {{ kindLabel(entry.kind) }}
          </span>
          <span class="history__tag">{{ entry.tag }}</span>
        </router-link>
        <button
          type="button"
          class="history__remove"
          :aria-label="`删除 ${entry.tag}`"
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
  clearHistory,
  readHistory,
  removeHistory,
  type HistoryEntry,
  type HistoryKind,
} from '../utils/searchHistory'

const entries = ref<HistoryEntry[]>([])

/** 刷新列表。localStorage 是同步的，直接重读即可。 */
function refresh() {
  entries.value = readHistory()
}

onMounted(refresh)

function kindLabel(kind: HistoryKind): string {
  return kind === 'clan' ? '部落' : '玩家'
}

function routeFor(entry: HistoryEntry) {
  return {
    name: entry.kind === 'clan' ? 'clan' : 'player',
    params: { tag: entry.tag },
  }
}

function onRemove(entry: HistoryEntry) {
  removeHistory(entry.tag, entry.kind)
  refresh()
}

function onClear() {
  clearHistory()
  refresh()
}
</script>

<style scoped>
.history {
  margin-top: 24px;
}
.history__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.history__title {
  font-size: 0.875rem;
  color: var(--text-secondary);
}
.history__clear {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 0.875rem;
  color: var(--text-secondary);
  padding: 0;
}
.history__clear:hover {
  color: var(--accent-gold);
}
.history__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.history__item {
  display: flex;
  align-items: center;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.history__link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  color: var(--text-primary);
  text-decoration: none;
  font-size: 0.875rem;
}
.history__link:hover {
  color: var(--accent-gold);
}
.history__kind {
  font-size: 0.75rem;
  padding: 0 5px;
  border-radius: 4px;
  line-height: 16px;
}
.history__kind--player {
  background: #e0a03026;
  color: var(--accent-gold);
}
.history__kind--clan {
  background: #3ad1c026;
  color: var(--tier-b);
}
.history__remove {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--text-faint);
  padding: 4px 10px 4px 0;
  font-size: 0.8125rem;
}
.history__remove:hover {
  color: var(--accent-danger);
}
</style>
