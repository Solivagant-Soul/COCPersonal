<template>
  <el-table :data="rows" class="ranking-table" stripe>
    <el-table-column label="排名" prop="rank" width="80" />
    <el-table-column label="名称">
      <template #default="{ row }">
        <router-link :to="detailRoute(row)">{{ row.name || row.tag }}</router-link>
      </template>
    </el-table-column>
    <el-table-column label="标签" prop="tag" width="150" />
    <el-table-column v-for="col in metricColumns" :key="col.prop" :label="col.label">
      <template #default="{ row }">{{ formatNumber(row[col.prop]) }}</template>
    </el-table-column>
    <template #empty>暂无数据</template>
  </el-table>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { RankingKind, RankingRow } from '../api/endpoints'
import { formatNumber } from '../utils/format'

const props = defineProps<{ rows: RankingRow[]; kind: RankingKind }>()

/** 每种榜单看哪些指标 —— 与后端 rankings.py 的 _METRICS_BY_KIND 一致。 */
const METRIC_COLUMNS: Record<RankingKind, Array<{ label: string; prop: string }>> = {
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

const PLAYER_KINDS: RankingKind[] = ['players']

const metricColumns = computed(() => METRIC_COLUMNS[props.kind] ?? [])

function detailRoute(row: RankingRow) {
  return PLAYER_KINDS.includes(props.kind)
    ? { name: 'player', params: { tag: row.tag } }
    : { name: 'clan', params: { tag: row.tag } }
}
</script>
