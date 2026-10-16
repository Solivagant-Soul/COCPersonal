<template>
  <div class="page">
    <h2>排行榜</h2>

    <div class="toolbar">
      <el-select v-model="locationId" placeholder="选择地区" class="toolbar__select">
        <el-option
          v-for="loc in locations"
          :key="loc.id"
          :label="loc.name"
          :value="loc.id"
        />
      </el-select>

      <el-radio-group v-model="kind">
        <el-radio-button v-for="opt in KIND_OPTIONS" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <LoadingBlock v-if="loading" />
    <ErrorCard v-else-if="error" :error="error" @retry="fetchRankings" />

    <template v-else>
      <RankingTable :rows="rows" :kind="kind" />
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        class="pager"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="fetchRankings"
        @size-change="onSizeChange"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import {
  getLocations,
  getRankings,
  type Location,
  type RankingKind,
  type RankingRow,
} from '../api/endpoints'
import { ApiError } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import RankingTable from '../components/RankingTable.vue'

/** 夹具与官方一致：32000001 = China。找不到就退回列表第一个。 */
const DEFAULT_LOCATION_ID = 32000001

const KIND_OPTIONS: Array<{ value: RankingKind; label: string }> = [
  { value: 'clans', label: '部落' },
  { value: 'players', label: '玩家' },
  { value: 'capitals', label: '都城' },
  { value: 'clans_builder_base', label: '部落基地' },
  { value: 'players_builder_base', label: '玩家基地' },
]

const locations = ref<Location[]>([])
const locationId = ref<number | null>(null)
const kind = ref<RankingKind>('clans')

const rows = ref<RankingRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const loading = ref(false)
const error = ref<ApiError | null>(null)

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError('UNKNOWN_ERROR', '请求失败', 0)
}

async function loadLocations() {
  try {
    const res = await getLocations()
    locations.value = res.data.items
    const preferred = locations.value.find((l) => l.id === DEFAULT_LOCATION_ID)
    locationId.value = preferred?.id ?? locations.value[0]?.id ?? null
  } catch (err) {
    error.value = toApiError(err)
  }
}

async function fetchRankings() {
  if (locationId.value === null) return
  loading.value = true
  error.value = null
  try {
    const res = await getRankings(kind.value, locationId.value, page.value, pageSize.value)
    rows.value = res.data.items
    total.value = res.data.total
  } catch (err) {
    error.value = toApiError(err)
  } finally {
    loading.value = false
  }
}

function onSizeChange() {
  page.value = 1
  void fetchRankings()
}

// 切地区或切榜单类型都回到第 1 页重拉
watch([kind, locationId], () => {
  page.value = 1
  void fetchRankings()
})

// 只加载地区；locationId 一旦就位，上面的 watch 会发出第一次拉取
onMounted(loadLocations)
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.toolbar__select {
  width: 220px;
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
