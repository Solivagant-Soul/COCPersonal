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

        <!--
          战报是可选区块：请求失败时 battleRows 为 null，整块不出现。
          空列表才显示空态 —— 「没有战报」和「拿不到战报」是两件事。
        -->
        <template v-if="battleRows !== null">
          <hr class="page-card__divider page-card__divider--bottom" />
          <div class="battle-panel">
            <div class="battle-panel__head">
              <h3 class="battle-panel__title">传奇联赛战报</h3>
              <p v-if="battleSummary" class="battle-summary">{{ battleSummary }}</p>
            </div>

            <ul v-if="battleRows.length" class="battle-list">
              <li v-for="row in battleRows" :key="row.key" class="battle-row">
                <span
                  class="battle-row__kind"
                  :class="`battle-row__kind--${row.kind}`"
                >{{ row.kindLabel }}</span>
                <span class="battle-row__stars">{{ row.stars }}</span>
                <span class="battle-row__destruction">{{ row.destruction }}</span>
                <span v-if="row.units.length" class="battle-row__army">
                  <UnitLevelTile
                    v-for="(unit, unitIndex) in row.units"
                    :key="`${unit.name}-${unitIndex}`"
                    :asset="unit.asset"
                    :name="unit.name"
                    :level="unit.level"
                    :max-level="unit.maxLevel"
                    size="small"
                  />
                </span>
                <span class="battle-row__time">{{ row.time }}</span>
              </li>
            </ul>

            <p v-else class="battle-panel__empty">该玩家最近没有传奇联赛战报</p>
          </div>
        </template>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  getPlayer,
  getPlayerBattles,
  type PlayerBattle,
  type PlayerProfile,
} from '../api/endpoints'
import { ApiError, type Meta } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import FollowButton from '../components/FollowButton.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import StatGrid from '../components/StatGrid.vue'
import type { StatItem } from '../components/statItem'
import UnitLevelTile from '../components/UnitLevelTile.vue'
import { isHomeVillage, lookupUnitAsset, type UnitAsset } from '../data/unitAssets'
import {
  enumLabel,
  formatLeagueName,
  formatNumber,
  formatShortBeijingTime,
} from '../utils/format'

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

/** 已取到的战报；`null` = 还在请求或请求失败 —— 两种情况都不渲染区块。 */
const battles = ref<PlayerBattle[] | null>(null)

interface BattleRowView {
  key: string
  kind: 'attack' | 'defense'
  kindLabel: string
  stars: string
  destruction: string
  time: string
  units: UnitView[]
}

/** 一支队伍里的兵种 / 法术 / 英雄，顺序与练度区一致，夜世界单位照旧过滤。 */
function battleUnits(army: PlayerBattle['army']): UnitView[] {
  if (!army) return []
  const groups = [
    { key: 'troops', rows: army.troops },
    { key: 'spells', rows: army.spells },
    { key: 'heroes', rows: army.heroes },
  ] as const

  return groups.flatMap((group) =>
    (group.rows ?? [])
      .filter((row) => isHomeVillage(row.village))
      .map<UnitView>((row) => ({
        name: row.name,
        asset: lookupUnitAsset(group.key, row.name),
        level: typeof row.level === 'number' ? row.level : null,
        maxLevel: typeof row.maxLevel === 'number' ? row.maxLevel : null,
      })),
  )
}

/** 星级用实心星表示；0 星写「0 星」，免得空串让人以为数据没加载出来。 */
function formatStars(stars: number | null | undefined): string {
  if (typeof stars !== 'number' || !Number.isFinite(stars)) return '-'
  const n = Math.max(0, Math.min(3, Math.round(stars)))
  return n === 0 ? '0 星' : '★'.repeat(n)
}

const battleRows = computed<BattleRowView[] | null>(() => {
  const rows = battles.value
  if (!rows) return null
  return rows.map((battle, index) => ({
    // 上游时间可能重复（同一秒的两条），索引兜底保证 key 唯一
    key: `${battle.timestamp ?? ''}-${battle.opponent?.tag ?? ''}-${index}`,
    kind: battle.kind,
    kindLabel: battle.kind === 'attack' ? '进攻' : '防守',
    stars: formatStars(battle.stars),
    destruction:
      typeof battle.destructionPercentage === 'number'
        ? `${battle.destructionPercentage}%`
        : '-',
    time: formatShortBeijingTime(battle.timestamp),
    units: battleUnits(battle.army),
  }))
})

/**
 * 汇总只统计**进攻**：防守条目上的星是对方打出来的，混进来算「三星率」
 * 会把玩家的表现算错。没有进攻记录就不显示汇总。
 */
const battleSummary = computed<string | null>(() => {
  const attacks = (battles.value ?? []).filter((battle) => battle.kind === 'attack')
  if (!attacks.length) return null

  const threeStar = attacks.filter((battle) => (battle.stars ?? 0) >= 3).length
  const rate = Math.round((threeStar / attacks.length) * 100)
  const destructions = attacks
    .map((battle) => battle.destructionPercentage)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const average = destructions.length
    ? Math.round(destructions.reduce((sum, value) => sum + value, 0) / destructions.length)
    : null

  const tail = average === null ? '' : ` · 场均摧毁 ${average}%`
  return `进攻 ${attacks.length} 场 · 三星率 ${rate}%${tail}`
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
  battles.value = null
  // 战报与档案并行拉：慢一点不该拖住档案，失败也不该影响档案
  void loadBattles(tag)
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

async function loadBattles(tag: string) {
  try {
    const res = await getPlayerBattles(tag)
    // 请求期间路由可能已经切走，别把上一个玩家的战报写进当前页
    if (String(route.params.tag ?? '') !== tag) return
    battles.value = res.data.items ?? []
  } catch {
    // 可选区块：拿不到就整块不显示，不弹错误、不影响整页
    battles.value = null
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

/* 战报区：与练度区共用同一张卡，靠同款分隔线隔开 */
.battle-panel__head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 12px;
}
.battle-panel__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.battle-summary {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-secondary);
}

.battle-list {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}
.battle-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 9px 0;
  border-top: 1px solid var(--border-default);
}
.battle-row:first-child {
  padding-top: 2px;
  border-top: none;
}

.battle-row__kind {
  flex-shrink: 0;
  padding: 1px 6px;
  border: 1px solid var(--border-default);
  border-radius: 4px;
  font-size: 0.75rem;
  line-height: 1.4;
  color: var(--text-secondary);
}
/* 进攻是我们关心的那一侧，用金色区分；防守保持中性灰 */
.battle-row__kind--attack {
  border-color: var(--accent-gold);
  color: var(--accent-gold);
}

.battle-row__stars {
  flex-shrink: 0;
  /* 固定成三颗星的宽度：星级不同的行里，队伍图标才能竖着对齐 */
  min-width: 38px;
  font-size: 0.875rem;
  letter-spacing: 1px;
  color: var(--accent-gold-bright);
}
.battle-row__destruction {
  flex-shrink: 0;
  min-width: 42px;
  font-size: 0.8125rem;
  color: var(--text-secondary);
}
.battle-row__army {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
/* 时间靠右：换行时也停在行的末尾 */
.battle-row__time {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--text-faint);
}

.battle-panel__empty {
  margin: 12px 0 0;
  font-size: 0.875rem;
  color: var(--text-faint);
}
</style>
