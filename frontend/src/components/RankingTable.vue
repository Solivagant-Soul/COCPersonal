<template>
  <div v-if="!rows.length" class="ranking-empty">暂无数据</div>

  <ul v-else class="ranking-list">
    <li v-for="row in rows" :key="row.tag" class="ranking-card">
      <div class="ranking-card__rank">
        <span class="ranking-card__num" :class="tierClass(row.rank)">{{ row.rank }}</span>
        <span v-if="tierLabel(row.rank)" class="ranking-card__tier" :class="tierClass(row.rank)">
          {{ tierLabel(row.rank) }}
        </span>
      </div>

      <div class="ranking-card__main">
        <router-link :to="detailRoute(row)" class="ranking-card__name">
          {{ row.name || row.tag }}
        </router-link>
        <div class="ranking-card__meta">
          <span class="ranking-card__tag">{{ row.tag }}</span>
          <span v-if="row.clanName" class="ranking-card__clan">{{ row.clanName }}</span>
        </div>
      </div>

      <div class="ranking-card__stats">
        <div v-for="col in metricColumns" :key="col.prop" class="ranking-card__stat">
          <span class="ranking-card__stat-label">{{ col.label }}</span>
          <span class="ranking-card__stat-value">{{ formatNumber(row[col.prop]) }}</span>
        </div>
      </div>

      <div class="ranking-card__delta" :class="deltaClass(row)">
        <template v-if="deltaText(row)">{{ deltaText(row) }}</template>
      </div>
    </li>
  </ul>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { RankingEntity, RankingMetric, RankingRow } from '../api/endpoints'
import { formatNumber } from '../utils/format'

const props = defineProps<{ rows: RankingRow[]; entity: RankingEntity }>()

/** 每种榜单看哪些指标 —— 与后端 rankings.py 的 _METRICS_BY_KIND 一致。 */
const METRIC_COLUMNS: Record<RankingEntity, Array<{ label: string; prop: RankingMetric }>> = {
  clans: [
    { label: '积分', prop: 'points' },
    { label: '成员', prop: 'members' },
    { label: '等级', prop: 'clanLevel' },
  ],
  players: [
    { label: '奖杯', prop: 'trophies' },
    { label: '等级', prop: 'expLevel' },
  ],
}

const PLAYER_ENTITIES: RankingEntity[] = ['players']

const metricColumns = computed(() => METRIC_COLUMNS[props.entity] ?? [])

/**
 * 名次梯级：前 1 名 OP、前 3 名 S、4-10 名 A、其余 B。
 * 徽章颜色取自参考站的金/橙/青三色。
 */
function tierClass(rank: number): string {
  if (rank <= 1) return 'tier-op'
  if (rank <= 3) return 'tier-s'
  if (rank <= 10) return 'tier-a'
  return 'tier-b'
}

function tierLabel(rank: number): string {
  if (rank <= 1) return 'OP'
  if (rank <= 3) return 'S'
  if (rank <= 10) return 'A'
  return ''
}

/**
 * 名次涨跌。``previousRank`` 是上一次的名次：比上次小 = 上升。
 * 官方对新上榜的条目给 null，那就不显示箭头（不是「跌到底」）。
 */
function deltaText(row: RankingRow): string {
  if (row.previousRank === null || row.previousRank === undefined) return ''
  const diff = row.previousRank - row.rank
  if (diff === 0) return '—'
  return diff > 0 ? `▲ ${diff}` : `▼ ${Math.abs(diff)}`
}

function deltaClass(row: RankingRow): string {
  if (row.previousRank === null || row.previousRank === undefined) return ''
  const diff = row.previousRank - row.rank
  if (diff === 0) return 'delta-flat'
  return diff > 0 ? 'delta-up' : 'delta-down'
}

function detailRoute(row: RankingRow) {
  return PLAYER_ENTITIES.includes(props.entity)
    ? { name: 'player', params: { tag: row.tag } }
    : { name: 'clan', params: { tag: row.tag } }
}
</script>

<style scoped>
.ranking-empty {
  padding: 48px 0;
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
}

.ranking-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* ---- 卡片 ---- */
.ranking-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
}
.ranking-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
  box-shadow: var(--shadow-card-hover);
}

/* ---- 名次 ---- */
.ranking-card__rank {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 84px;
  flex-shrink: 0;
}
.ranking-card__num {
  font-size: 22px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  min-width: 30px;
  text-align: right;
}
.ranking-card__tier {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.5px;
  line-height: 16px;
}

/* 梯级配色：名次数字与徽章同色，徽章另有底色 */
.ranking-card__num.tier-op,
.ranking-card__tier.tier-op {
  color: var(--accent-gold-bright);
}
.ranking-card__tier.tier-op {
  background: #e0a03026;
}
.ranking-card__num.tier-s,
.ranking-card__tier.tier-s {
  color: var(--tier-s);
}
.ranking-card__tier.tier-s {
  background: #ff8a0026;
}
.ranking-card__num.tier-a,
.ranking-card__tier.tier-a {
  color: var(--tier-b);
}
.ranking-card__tier.tier-a {
  background: #3ad1c026;
}
.ranking-card__num.tier-b {
  color: var(--text-secondary);
}

/* ---- 主体 ---- */
.ranking-card__main {
  flex: 1;
  min-width: 0;
}
.ranking-card__name {
  display: block;
  color: var(--text-primary);
  text-decoration: none;
  font-weight: 600;
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ranking-card__name:hover {
  color: var(--accent-gold);
}
.ranking-card__meta {
  display: flex;
  gap: 10px;
  font-size: 12px;
  color: var(--text-faint);
  margin-top: 2px;
}
.ranking-card__tag {
  font-variant-numeric: tabular-nums;
}

/* ---- 指标 ---- */
.ranking-card__stats {
  display: flex;
  gap: 24px;
  flex-shrink: 0;
}
.ranking-card__stat {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  min-width: 56px;
}
.ranking-card__stat-label {
  font-size: 11px;
  color: var(--text-faint);
}
.ranking-card__stat-value {
  font-size: 15px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}

/* ---- 涨跌 ---- */
.ranking-card__delta {
  width: 64px;
  text-align: right;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.delta-up {
  color: var(--accent-positive);
}
.delta-down {
  color: var(--accent-danger);
}
.delta-flat {
  color: var(--text-faint);
}

/* ---- 窄屏：指标换行到下面 ---- */
@media (max-width: 640px) {
  .ranking-card {
    flex-wrap: wrap;
    gap: 10px;
  }
  .ranking-card__stats {
    width: 100%;
    justify-content: flex-start;
    gap: 20px;
  }
  .ranking-card__stat {
    align-items: flex-start;
  }
  .ranking-card__delta {
    width: auto;
  }
}
</style>
