<template>
  <div class="page">
    <h2>玩家详情</h2>

    <LoadingBlock v-if="loading" />
    <ErrorCard v-else-if="error" :error="error" @retry="load" />

    <template v-else-if="profile">
      <el-alert
        v-if="isStale"
        type="warning"
        :closable="false"
        show-icon
        title="数据可能过期"
        description="上游暂时不可用，下面是最近一次成功采集的数据。"
      />

      <div class="detail-card">
        <div class="profile-head">
          <span class="profile-head__name">{{ profile.name || profile.tag }}</span>
          <span class="profile-head__tag">{{ profile.tag }}</span>
        </div>

        <div class="meta-line">缓存状态：{{ meta?.cache ?? '-' }}</div>

        <StatGrid :items="stats" />

        <div v-if="profile.clan" class="clan-ref">
          所属部落：
          <router-link :to="{ name: 'clan', params: { tag: profile.clan.tag } }">
            {{ profile.clan.name || profile.clan.tag }}
          </router-link>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { getPlayer, type PlayerProfile } from '../api/endpoints'
import { ApiError, type Meta } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import StatGrid from '../components/StatGrid.vue'
import { enumLabel, formatNumber } from '../utils/format'

const route = useRoute()

const loading = ref(false)
const error = ref<ApiError | null>(null)
const profile = ref<PlayerProfile | null>(null)
const meta = ref<Meta | null>(null)

const isStale = computed(() => meta.value?.cache === 'STALE')

const stats = computed(() => {
  const p = profile.value
  if (!p) return []
  return [
    { label: '等级', value: formatNumber(p.expLevel) },
    { label: '奖杯', value: formatNumber(p.trophies) },
    { label: '最高奖杯', value: formatNumber(p.bestTrophies) },
    { label: '大本营', value: formatNumber(p.townHallLevel) },
    { label: '战争之星', value: formatNumber(p.warStars) },
    { label: '部落角色', value: enumLabel('role', p.role) },
  ]
})

async function load() {
  const tag = String(route.params.tag ?? '')
  loading.value = true
  error.value = null
  profile.value = null
  meta.value = null
  try {
    const res = await getPlayer(tag)
    profile.value = res.data
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
.profile-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 16px 0 4px;
}
.profile-head__name {
  font-size: 1.5rem;
  font-weight: 600;
}
.profile-head__tag {
  color: var(--text-secondary);
}
.meta-line {
  color: var(--text-secondary);
  font-size: 0.8125rem;
  margin-bottom: 8px;
}
.clan-ref {
  margin-top: 8px;
}
</style>
