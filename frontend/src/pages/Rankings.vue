<template>
  <div class="page">
    <section class="page-card">
      <h2 class="page-card__title">排行榜</h2>
      <p class="page-card__lead">
        查看全服部落与玩家的实时排名，或按赛季快照翻看历史榜单。
      </p>

      <el-tabs v-model="view">
        <!--
          实时榜：两套状态与赛季面板完全独立 —— 共用 entity / page / rows 的话，
          在赛季面板切部落/玩家会把实时榜也重拉一遍，两个 loading 还会互相覆盖。
        -->
        <el-tab-pane label="实时榜" name="realtime">
          <p class="page__hint">
            全服 · 线上经 RoyaleAPI 代理，约每 6 小时刷新
            <span v-if="realtimeFetchedAt" class="page__stamp">
              数据更新于 {{ formatBeijingTime(realtimeFetchedAt) }}
            </span>
          </p>

          <div class="toolbar">
            <el-radio-group v-model="realtimeEntity">
              <el-radio-button v-for="opt in ENTITY_OPTIONS" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </el-radio-button>
            </el-radio-group>
          </div>

          <LoadingBlock v-if="realtimeLoading" />
          <ErrorCard v-else-if="realtimeError" :error="realtimeError" @retry="fetchRealtime" />

          <template v-else>
            <RankingTable :rows="realtimeRows" :entity="realtimeEntity" />
            <el-pagination
              v-model:current-page="realtimePage"
              v-model:page-size="realtimePageSize"
              class="pager"
              :page-sizes="[20, 50, 100]"
              :total="realtimeTotal"
              layout="total, sizes, prev, pager, next"
              @current-change="fetchRealtime"
              @size-change="onRealtimeSizeChange"
            />
          </template>
        </el-tab-pane>

        <!-- 必须 lazy：否则首屏会把两个面板都挂上，白打一次赛季接口。 -->
        <el-tab-pane label="赛季榜" name="season" lazy>
          <p class="page__hint">按赛季快照查看历史榜单，数据来自 War Report。</p>

          <div class="toolbar">
            <el-select
              v-model="seasonSnapshot"
              class="season-select"
              placeholder="选择赛季"
              :disabled="!seasons.length"
            >
              <el-option
                v-for="s in seasons"
                :key="s.seasonId"
                :label="s.seasonId"
                :value="s.seasonId"
              />
            </el-select>

            <el-radio-group v-model="seasonEntity">
              <el-radio-button v-for="opt in ENTITY_OPTIONS" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </el-radio-button>
            </el-radio-group>
          </div>

          <LoadingBlock v-if="seasonsLoading || seasonLoading" />
          <ErrorCard v-else-if="seasonsError" :error="seasonsError" @retry="loadSeasons" />
          <ErrorCard v-else-if="seasonError" :error="seasonError" @retry="fetchSeason" />
          <div v-else-if="!seasons.length" class="season-empty">暂无赛季数据</div>

          <template v-else>
            <RankingTable :rows="seasonRows" :entity="seasonEntity" />
            <el-pagination
              v-model:current-page="seasonPage"
              v-model:page-size="seasonPageSize"
              class="pager"
              :page-sizes="[20, 50, 100]"
              :total="seasonTotal"
              layout="total, sizes, prev, pager, next"
              @current-change="fetchSeason"
              @size-change="onSeasonSizeChange"
            />
          </template>

          <!-- 署名固定渲染，空列表也要有 -->
          <SourceNote class="season-source" />
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import {
  GLOBAL_LOCATION_ID,
  getRankings,
  getWarReportSeasonRankings,
  getWarReportSeasons,
  type RankingEntity,
  type RankingRow,
  type WarReportSeason,
} from '../api/endpoints'
import { ApiError } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import RankingTable from '../components/RankingTable.vue'
import SourceNote from '../components/SourceNote.vue'
import { formatBeijingTime } from '../utils/format'

type RankingView = 'realtime' | 'season'

const ENTITY_OPTIONS: Array<{ value: RankingEntity; label: string }> = [
  { value: 'clans', label: '部落' },
  { value: 'players', label: '玩家' },
]

const view = ref<RankingView>('realtime')

/* ---- 实时榜 ---- */
const realtimeEntity = ref<RankingEntity>('clans')
const realtimeRows = ref<RankingRow[]>([])
const realtimeTotal = ref(0)
const realtimePage = ref(1)
const realtimePageSize = ref(20)
const realtimeLoading = ref(false)
const realtimeError = ref<ApiError | null>(null)
/** 这批实时榜数据的抓取时间（`meta.fetchedAt`）。null = 还不知道，不显示。 */
const realtimeFetchedAt = ref<string | null>(null)

/* ---- 赛季榜 ---- */
const seasonEntity = ref<RankingEntity>('clans')
const seasonRows = ref<RankingRow[]>([])
const seasonTotal = ref(0)
const seasonPage = ref(1)
const seasonPageSize = ref(20)
const seasonLoading = ref(false)
const seasonError = ref<ApiError | null>(null)

const seasons = ref<WarReportSeason[]>([])
/** 当前选中的赛季快照；列表为空时是 null，此时不发榜请求。 */
const seasonSnapshot = ref<string | null>(null)
const seasonsLoading = ref(false)
const seasonsError = ref<ApiError | null>(null)
/** 赛季列表只在第一次切到赛季面板时拉一次，切来切去不重复请求。 */
const seasonsLoaded = ref(false)

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError('UNKNOWN_ERROR', '请求失败', 0)
}

/**
 * 请求序号闸门：**只有最后发出的那一次请求能写状态**。
 *
 * 切类型 / 翻页 / 改页长都比一次请求快，先发的可能后回来。没有闸门时，
 * 晚到的旧响应会盖掉新响应：列表停在旧的类型或旧的页，分页器却显示新的，
 * 而且**不会自愈** —— 用户不动手就一直是错的。错误同理：旧请求的失败不该
 * 盖掉新请求已经拿到的数据。
 */
let realtimeSeq = 0
let seasonSeq = 0

async function fetchRealtime() {
  const seq = ++realtimeSeq
  realtimeLoading.value = true
  realtimeError.value = null
  try {
    const res = await getRankings(
      realtimeEntity.value,
      GLOBAL_LOCATION_ID,
      realtimePage.value,
      realtimePageSize.value,
    )
    if (seq !== realtimeSeq) return
    realtimeRows.value = res.data.items
    realtimeTotal.value = res.data.total
    // 契约 §6.2 要求实时榜显示 meta.fetchedAt：这是「榜单多久以前抓的」，
    // 与提示里的「约每 6 小时」配合，用户才知道现在看的是不是旧数。
    realtimeFetchedAt.value = res.meta.fetchedAt
  } catch (err) {
    if (seq !== realtimeSeq) return
    realtimeError.value = toApiError(err)
  } finally {
    // loading 也只能由最新一次熄灭：旧请求在 finally 里无条件置 false，
    // 会把还在飞的新请求的 loading 提前关掉（用户看到"加载完了"却是旧列表）。
    if (seq === realtimeSeq) realtimeLoading.value = false
  }
}

function onRealtimeSizeChange() {
  realtimePage.value = 1
  void fetchRealtime()
}

// 切榜单类型回到第 1 页重拉
watch(realtimeEntity, () => {
  realtimePage.value = 1
  void fetchRealtime()
})

async function loadSeasons() {
  seasonsLoading.value = true
  seasonsError.value = null
  try {
    const res = await getWarReportSeasons()
    seasons.value = res.data.items
    seasonSnapshot.value = seasons.value[0]?.seasonId ?? null
  } catch (err) {
    seasonsError.value = toApiError(err)
  } finally {
    seasonsLoading.value = false
    seasonsLoaded.value = true
  }
}

async function fetchSeason() {
  // 没有赛季可选时不该发榜请求
  if (seasonSnapshot.value === null) return
  const seq = ++seasonSeq
  seasonLoading.value = true
  seasonError.value = null
  try {
    const res = await getWarReportSeasonRankings(
      seasonSnapshot.value,
      seasonEntity.value,
      seasonPage.value,
      seasonPageSize.value,
    )
    if (seq !== seasonSeq) return
    seasonRows.value = res.data.items
    seasonTotal.value = res.data.total
  } catch (err) {
    if (seq !== seasonSeq) return
    seasonError.value = toApiError(err)
  } finally {
    if (seq === seasonSeq) seasonLoading.value = false
  }
}

function onSeasonSizeChange() {
  seasonPage.value = 1
  void fetchSeason()
}

// 换赛季或换部落/玩家都回到第 1 页重拉
watch([seasonSnapshot, seasonEntity], () => {
  if (seasonSnapshot.value === null) return
  seasonPage.value = 1
  void fetchSeason()
})

watch(view, (next) => {
  if (next === 'season' && !seasonsLoaded.value) {
    void loadSeasons()
  }
})

onMounted(fetchRealtime)
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.pager {
  margin-top: 20px;
  justify-content: flex-end;
}
/* 赛季下拉固定宽度：不固定时 Element Plus 的 select 会撑满整行，
 * 把「部落 / 玩家」挤到下一行，工具栏看起来像断了一截。 */
.season-select {
  width: 240px;
}
/* 抓取时间：比提示语更弱一档，不跟正文抢注意力 */
.page__stamp {
  display: inline-block;
  margin-left: 8px;
  color: var(--text-faint);
  font-size: 0.8125rem;
}
.season-empty {
  padding: 48px 0;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.9375rem;
}
.season-source {
  margin-top: 16px;
}
</style>
