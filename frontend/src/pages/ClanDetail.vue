<template>
  <div class="page">
    <section class="page-card">
      <button type="button" class="page-back" @click="goBack">← 返回</button>

      <div class="page-head">
        <!-- 徽章缺图时不占位，标题照常靠左 -->
        <img
          v-if="badgeUrl"
          class="clan-badge"
          :src="badgeUrl"
          :alt="clan ? `${clan.name || clan.tag} 部落徽章` : '部落徽章'"
          loading="lazy"
          decoding="async"
        />
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

        <!-- 成员是附属信息：拉不到就整块不出现，绝不影响上面的档案 -->
        <template v-if="members !== null">
          <hr class="page-card__divider" />
          <section class="member-panel">
            <h3 class="member-panel__title">成员 · {{ members.length }} 人</h3>

            <p v-if="memberRows.length === 0" class="member-panel__empty">暂无成员数据</p>

            <div v-else class="member-table-wrap">
              <table class="member-table">
                <thead>
                  <tr>
                    <th class="member-cell--rank">#</th>
                    <th>玩家</th>
                    <th>职位</th>
                    <th class="member-cell--th">大本</th>
                    <th>段位</th>
                    <th class="member-cell--donations">捐兵</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in memberRows" :key="row.tag" class="member-row">
                    <td class="member-cell--rank">
                      <span class="member-rank-pos">{{ row.rank }}</span>
                      <span
                        v-if="row.delta"
                        class="member-rank-delta"
                        :class="`member-rank-delta--${row.deltaKind}`"
                        >{{ row.delta }}</span
                      >
                    </td>
                    <td>
                      <RouterLink
                        class="member-name"
                        :to="{ name: 'player', params: { tag: row.tag } }"
                        >{{ row.name }}</RouterLink
                      >
                      <span class="member-tag">{{ row.tag }}</span>
                    </td>
                    <td class="member-cell__role">{{ row.roleLabel }}</td>
                    <td class="member-cell__th">{{ row.townHall }}</td>
                    <td class="member-cell__league">
                      <img
                        v-if="row.leagueIcon"
                        class="member-league-icon"
                        :src="row.leagueIcon"
                        alt=""
                        loading="lazy"
                        decoding="async"
                      />
                      <span>{{ row.leagueLabel }}</span>
                    </td>
                    <td class="member-cell__donations">{{ row.donations }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  getClan,
  getClanMembers,
  type ClanDetail,
  type ClanMemberRow,
} from '../api/endpoints'
import { ApiError, type Meta } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import FollowButton from '../components/FollowButton.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import StatGrid from '../components/StatGrid.vue'
import { enumLabel, formatLeagueName, formatNumber } from '../utils/format'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const error = ref<ApiError | null>(null)
const clan = ref<ClanDetail | null>(null)
const meta = ref<Meta | null>(null)
/** `null` = 还没拿到（或请求失败），此状态下整块成员区不渲染。 */
const members = ref<ClanMemberRow[] | null>(null)

const isStale = computed(() => meta.value?.cache === 'STALE')

const badgeUrl = computed(() => {
  const urls = clan.value?.badgeUrls
  return urls?.small || urls?.medium || urls?.large || ''
})

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

/** 名次变化：previous - current > 0 是前进（↑N），反之后退（↓N）。 */
function rankDelta(row: ClanMemberRow): { text: string; kind: string } | null {
  const now = row.clanRank
  const before = row.previousClanRank
  if (typeof now !== 'number' || typeof before !== 'number') return null
  const diff = before - now
  if (diff > 0) return { text: `↑${diff}`, kind: 'up' }
  if (diff < 0) return { text: `↓${-diff}`, kind: 'down' }
  return null
}

const memberRows = computed(() => {
  return (members.value ?? []).map((row) => {
    const delta = rankDelta(row)
    const leagueName = row.league?.name
    return {
      tag: row.tag,
      name: row.name || row.tag,
      rank: typeof row.clanRank === 'number' ? row.clanRank : '-',
      delta: delta?.text ?? '',
      deltaKind: delta?.kind ?? '',
      roleLabel: enumLabel('role', row.role),
      // 大本等级缺失时留 '-'，不编一个 TH0
      townHall: typeof row.townHallLevel === 'number' ? `TH${row.townHallLevel}` : '-',
      // 联赛维表可能是空的（本地无 Token 时尤其常见）：退化成奖杯数
      leagueLabel: leagueName
        ? formatLeagueName(leagueName)
        : `${formatNumber(row.trophies)} 杯`,
      leagueIcon: row.league?.iconUrls?.small ?? '',
      donations: `${formatNumber(row.donations)} / ${formatNumber(row.donationsReceived)}`,
    }
  })
})

async function loadMembers(tag: string) {
  try {
    const res = await getClanMembers(tag)
    // 路由已经换到别的部落时丢弃这次结果，避免旧数据盖新页面
    if (String(route.params.tag ?? '') !== tag) return
    members.value = res.data
  } catch {
    // 成员只是附属信息，失败就整块不显示，也不打断部落档案
    if (String(route.params.tag ?? '') === tag) members.value = null
  }
}

async function load() {
  const tag = String(route.params.tag ?? '')
  loading.value = true
  error.value = null
  clan.value = null
  meta.value = null
  members.value = null
  void loadMembers(tag)
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

.clan-badge {
  width: 64px;
  height: 64px;
  border-radius: var(--radius-sm);
  flex: none;
  object-fit: contain;
}

.clan-desc {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 0.9375rem;
  line-height: 1.7;
}

/* ---- 成员表 ---- */
.member-panel {
  margin-top: 4px;
}
.member-panel__title {
  margin: 16px 0 12px;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.member-panel__empty {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.875rem;
}

/* 窄屏不挤压页面：表格自身保持最小宽度，外层横向滚动 */
.member-table-wrap {
  overflow-x: auto;
}
.member-table {
  width: 100%;
  min-width: 640px;
  border-collapse: collapse;
  font-size: 0.875rem;
}
.member-table th,
.member-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border-default);
  white-space: nowrap;
}
.member-table th {
  color: var(--text-secondary);
  font-weight: 500;
  font-size: 0.8125rem;
}
.member-table tbody tr:hover {
  background: var(--surface-subtle);
}
.member-row:last-child td {
  border-bottom: none;
}

.member-cell--rank {
  width: 72px;
}
.member-rank-pos {
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.member-rank-delta {
  margin-left: 6px;
  font-size: 0.75rem;
}
.member-rank-delta--up {
  color: var(--accent-positive);
}
.member-rank-delta--down {
  color: var(--accent-danger);
}

.member-name {
  color: var(--text-primary);
  text-decoration: none;
}
.member-name:hover {
  color: var(--accent-gold);
}
.member-tag {
  display: block;
  color: var(--text-faint);
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
}

.member-cell__role {
  color: var(--text-secondary);
}
.member-cell__th {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.member-cell__league {
  color: var(--text-secondary);
}
.member-league-icon {
  width: 18px;
  height: 18px;
  vertical-align: -3px;
  margin-right: 6px;
}

.member-cell--donations {
  text-align: right;
}
.member-cell__donations {
  text-align: right;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
</style>
