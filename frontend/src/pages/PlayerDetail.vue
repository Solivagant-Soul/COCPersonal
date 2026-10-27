<template>
  <div class="page">
    <section class="page-card">
      <!-- 标题是档案的主身份：查到谁就显示谁，没名字退回标签 -->
      <h2 class="page-card__title">{{ profile ? profile.name || profile.tag : '玩家详情' }}</h2>
      <p class="page-card__lead">
        <template v-if="profile">{{ profile.tag }} · 缓存状态：{{ meta?.cache ?? '-' }}</template>
        <template v-else>按标签查询玩家档案，支持全角＃、小写、省略 #。</template>
      </p>

      <el-alert
        v-if="isStale"
        type="warning"
        :closable="false"
        show-icon
        title="数据可能过期"
        description="上游暂时不可用，下面是最近一次成功采集的数据。"
      />

      <LoadingBlock v-if="loading" />
      <ErrorCard v-else-if="error" :error="error" @retry="load" />

      <template v-else-if="profile">
        <hr class="page-card__divider" />
        <StatGrid :items="stats" />

        <div v-if="profile.clan" class="clan-ref">
          所属部落：
          <router-link :to="{ name: 'clan', params: { tag: profile.clan.tag } }">
            {{ profile.clan.name || profile.clan.tag }}
          </router-link>
        </div>
      </template>
    </section>
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
.clan-ref {
  margin-top: 8px;
}
</style>
