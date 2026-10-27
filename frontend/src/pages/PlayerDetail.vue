<template>
  <div class="page">
    <section class="page-card">
      <button type="button" class="page-back" @click="goBack">← 返回</button>

      <div class="page-head">
        <h2 class="page-card__title">{{ profile ? profile.name || profile.tag : '玩家详情' }}</h2>
        <FollowButton
          v-if="profile"
          :tag="profile.tag"
          kind="player"
          :name="profile.name"
        />
      </div>

      <p class="page-card__lead">
        <template v-if="profile">
          <span class="page-card__lead-main">
            {{ profile.tag }}
            <template v-if="profile.clan">
              ·
              <router-link class="clan-link" :to="{ name: 'clan', params: { tag: profile.clan.tag } }">
                {{ profile.clan.name || profile.clan.tag }}
              </router-link>
            </template>
          </span>
          <span class="page-card__lead-sub">缓存状态：{{ meta?.cache ?? '-' }}</span>
        </template>
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

        <!-- 练度区与档案同卡：分隔线之下接着排兵种图，不再另起一张卡 -->
        <template v-if="unitGroups.length">
          <hr class="page-card__divider page-card__divider--bottom" />
          <div v-for="group in unitGroups" :key="group.key" class="unit-group">
            <div class="unit-group__label">{{ group.label }}</div>
            <div class="unit-group__units">
              <UnitLevelTile
                v-for="unit in group.units"
                :key="unit.name"
                :asset="unit.asset"
                :name="unit.name"
                :level="unit.level"
                :max-level="unit.maxLevel"
              />
            </div>
          </div>
        </template>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getPlayer, type PlayerProfile } from '../api/endpoints'
import { ApiError, type Meta } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import FollowButton from '../components/FollowButton.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import StatGrid from '../components/StatGrid.vue'
import type { StatItem } from '../components/statItem'
import UnitLevelTile from '../components/UnitLevelTile.vue'
import { isHomeVillage, lookupUnitAsset, type UnitAsset } from '../data/unitAssets'
import { enumLabel, formatLeagueName, formatNumber } from '../utils/format'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const error = ref<ApiError | null>(null)
const profile = ref<PlayerProfile | null>(null)
const meta = ref<Meta | null>(null)

const isStale = computed(() => meta.value?.cache === 'STALE')

const stats = computed<StatItem[]>(() => {
  const p = profile.value
  if (!p) return []
  const league = p.league
  return [
    { label: '等级', value: formatNumber(p.expLevel) },
    // 「大本营」在「奖杯」前面：查档案的人先关心本数，再关心奖杯
    { label: '大本营', value: formatNumber(p.townHallLevel) },
    { label: '最高奖杯', value: formatNumber(p.bestTrophies) },
    { label: '奖杯', value: formatNumber(p.trophies) },
    { label: '战争之星', value: formatNumber(p.warStars) },
    { label: '部落角色', value: enumLabel('role', p.role) },
    {
      label: '联赛',
      value: formatLeagueName(league?.name),
      // 图标是官方 CDN（league_tiers.icon_urls）；没有就只显示文字，不留空框
      icon: league?.iconUrls?.small ?? null,
      iconAlt: league?.name ?? '联赛图标',
    },
  ]
})

interface UnitView {
  name: string
  asset: UnitAsset | null
  level: number | null
  maxLevel: number | null
}

/**
 * 练度分组。只留主村 —— 夜世界的单位在本地素材库里没有图，
 * 混进来会让整块变成一片灰色兜底格子。
 */
const unitGroups = computed<Array<{ key: string; label: string; units: UnitView[] }>>(() => {
  const p = profile.value
  if (!p) return []
  const defs = [
    { key: 'troops', label: '兵种', rows: p.troops },
    { key: 'spells', label: '法术', rows: p.spells },
    { key: 'heroes', label: '英雄', rows: p.heroes },
  ] as const

  return defs
    .map((def) => ({
      key: def.key,
      label: def.label,
      units: (def.rows ?? [])
        .filter((row) => isHomeVillage(row.village))
        .map<UnitView>((row) => ({
          name: row.name,
          asset: lookupUnitAsset(def.key, row.name),
          level: typeof row.level === 'number' ? row.level : null,
          maxLevel: typeof row.maxLevel === 'number' ? row.maxLevel : null,
        })),
    }))
    .filter((group) => group.units.length > 0)
})

/** 返回上一页。直接打开详情页（没有上一页）时回查询页，别把用户甩出站点。 */
function goBack() {
  if (window.history.length > 1) router.back()
  else router.push({ name: 'query' })
}

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

.page-card__lead-main {
  display: block;
}
.page-card__lead-sub {
  display: block;
  font-size: 0.8125rem;
  color: var(--text-faint);
}

.clan-link {
  color: var(--accent-gold);
  text-decoration: none;
}
.clan-link:hover {
  text-decoration: underline;
}

/* 统计区与练度区之间那道线：与统计区上方那条同款 */
.page-card__divider--bottom {
  margin: 24px 0 20px;
}

.unit-group + .unit-group {
  margin-top: 18px;
}
.unit-group__label {
  margin-bottom: 8px;
  font-size: 0.875rem;
  color: var(--text-secondary);
}
.unit-group__units {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
