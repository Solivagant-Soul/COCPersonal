<template>
  <div class="page">
    <section class="page-card">
      <button type="button" class="page-back" @click="goBack">← 返回</button>

      <div class="page-head">
        <!-- 标题是档案的主身份：查到谁就显示谁，没名字退回标签 -->
        <h2 class="page-card__title">{{ clan ? clan.name || clan.tag : '部落详情' }}</h2>
        <FollowButton v-if="clan" :tag="clan.tag" kind="clan" :name="clan.name" />
      </div>
      <p class="page-card__lead">
        <template v-if="clan">{{ clan.tag }} · 缓存状态：{{ meta?.cache ?? '-' }}</template>
        <template v-else>按标签查询部落档案，支持全角＃、小写、省略 #。</template>
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

      <template v-else-if="clan">
        <p v-if="clan.description" class="clan-desc">{{ clan.description }}</p>

        <hr class="page-card__divider" />
        <StatGrid :items="stats" />
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getClan, type ClanDetail } from '../api/endpoints'
import { ApiError, type Meta } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import FollowButton from '../components/FollowButton.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import StatGrid from '../components/StatGrid.vue'
import { enumLabel, formatNumber } from '../utils/format'

const route = useRoute()
const router = useRouter()

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

/** 返回上一页。直接打开详情页（没有上一页）时回查询页，别把用户甩出站点。 */
function goBack() {
  if (window.history.length > 1) router.back()
  else router.push({ name: 'query' })
}

watch(() => route.params.tag, load, { immediate: true })
</script>

<style scoped>
.page-back {
  border: none;
  background: none;
  padding: 0;
  margin-bottom: 10px;
  cursor: pointer;
  font-size: 0.875rem;
  color: var(--text-secondary);
}
.page-back:hover {
  color: var(--accent-gold);
}

/* 标题与关注按钮同一行；窄屏时按钮换行到标题下面 */
.page-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.clan-desc {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 0.9375rem;
  line-height: 1.7;
}
</style>
