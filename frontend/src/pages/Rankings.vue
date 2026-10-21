<template>
  <div class="page">
    <h2>排行榜</h2>
    <p class="page__hint">
      全服（{{ GLOBAL_LOCATION_ID }}）的部落榜与玩家榜。
    </p>

    <div class="toolbar">
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
  GLOBAL_LOCATION_ID,
  getRankings,
  type RankingKind,
  type RankingRow,
} from '../api/endpoints'
import { ApiError } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import RankingTable from '../components/RankingTable.vue'

const KIND_OPTIONS: Array<{ value: RankingKind; label: string }> = [
  { value: 'clans', label: '部落' },
  { value: 'players', label: '玩家' },
]

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

async function fetchRankings() {
  loading.value = true
  error.value = null
  try {
    const res = await getRankings(kind.value, GLOBAL_LOCATION_ID, page.value, pageSize.value)
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

// 切榜单类型回到第 1 页重拉
watch(kind, () => {
  page.value = 1
  void fetchRankings()
})

onMounted(fetchRankings)
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
