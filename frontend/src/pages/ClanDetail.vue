<template>
  <div class="page">
    <h2>部落详情</h2>

    <LoadingBlock v-if="loading" />
    <ErrorCard v-else-if="error" :error="error" @retry="load" />

    <template v-else-if="clan">
      <el-alert
        v-if="isStale"
        type="warning"
        :closable="false"
        show-icon
        title="数据可能过期"
        description="上游暂时不可用，下面是最近一次成功采集的数据。"
      />

      <div class="detail-card">
        <div class="clan-head">
          <span class="clan-head__name">{{ clan.name || clan.tag }}</span>
          <span class="clan-head__tag">{{ clan.tag }}</span>
        </div>

        <div class="meta-line">缓存状态：{{ meta?.cache ?? '-' }}</div>

        <p v-if="clan.description" class="clan-desc">{{ clan.description }}</p>

        <StatGrid :items="stats" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { getClan, type ClanDetail } from '../api/endpoints'
import { ApiError, type Meta } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import StatGrid from '../components/StatGrid.vue'
import { enumLabel, formatNumber } from '../utils/format'

const route = useRoute()

const loading = ref(false)
const error = ref<ApiError | null>(null)
const clan = ref<ClanDetail | null>(null)
const meta = ref<Meta | null>(null)

const isStale = computed(() => meta.value?.cache === 'STALE')

const stats = computed(() => {
  const c = clan.value
  if (!c) return []
  return [
    { label: '部落等级', value: formatNumber(c.clanLevel) },
    { label: '部落积分', value: formatNumber(c.clanPoints) },
    { label: '成员', value: formatNumber(c.members) },
    { label: '战争胜场', value: formatNumber(c.warWins) },
    { label: '战争败场', value: formatNumber(c.warLosses) },
    { label: '战争连胜', value: formatNumber(c.warWinStreak) },
    { label: '所需奖杯', value: formatNumber(c.requiredTrophies) },
    { label: '开战频率', value: enumLabel('warFrequency', c.warFrequency) },
  ]
})

async function load() {
  const tag = String(route.params.tag ?? '')
  loading.value = true
  error.value = null
  clan.value = null
  meta.value = null
  try {
    const res = await getClan(tag)
    clan.value = res.data
    meta.value = res.meta
  } catch (err) {
    error.value =
      err instanceof ApiError ? err : new ApiError('UNKNOWN_ERROR', '请求失败', 0)
  } finally {
    loading.value = false
  }
}

watch(() => route.params.tag, load, { immediate: true })
</script>

<style scoped>
.detail-card {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow-card);
}
.clan-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 16px 0 4px;
}
.clan-head__name {
  font-size: 1.5rem;
  font-weight: 600;
}
.clan-head__tag {
  color: var(--text-secondary);
}
.meta-line {
  color: var(--text-secondary);
  font-size: 0.8125rem;
  margin-bottom: 8px;
}
.clan-desc {
  color: var(--text-regular, #d4d4d8);
}
</style>
