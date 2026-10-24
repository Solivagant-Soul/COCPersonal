<template>
  <div class="page">
    <h2>阵容</h2>
    <p class="page__hint">数据来自 War Report，统计对象为前 200 名传奇联赛玩家</p>

    <LoadingBlock v-if="loading" />
    <ErrorCard v-else-if="error" :error="error" @retry="load" />

    <template v-else>
      <p v-if="!armies.length" class="armies-empty">暂无数据</p>
      <ul v-else class="army-grid">
        <li v-for="army in armies" :key="army.canonicalKey" class="army-card">
          <div class="army-card__head">
            <span class="army-card__name">{{ army.name }}</span>
            <span class="army-card__percentage">{{ army.percentage.toFixed(1) }}%</span>
          </div>

          <dl class="army-card__stats">
            <div class="army-card__stat">
              <dt>使用次数</dt>
              <dd>{{ army.useCount }}</dd>
            </div>
            <div class="army-card__stat">
              <dt>玩家数</dt>
              <dd>{{ army.playerCount }}</dd>
            </div>
            <div class="army-card__stat">
              <dt>平均星级</dt>
              <dd>{{ army.averageStars.toFixed(2) }}</dd>
            </div>
            <div class="army-card__stat">
              <dt>平均摧毁率</dt>
              <dd>{{ army.averageDestruction.toFixed(2) }}</dd>
            </div>
          </dl>

          <el-button
            class="army-card__copy"
            :aria-label="`复制 ${army.name} 的阵型链接`"
            @click="copyLink(army.armyLink)"
          >
            复制阵型链接
          </el-button>
        </li>
      </ul>
    </template>

    <!-- 署名固定渲染，加载中 / 出错 / 空列表都要有 -->
    <SourceNote class="armies-source" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getArmies, type ArmyRow } from '../api/endpoints'
import { ApiError } from '../api/request'
import ErrorCard from '../components/ErrorCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import SourceNote from '../components/SourceNote.vue'

const armies = ref<ArmyRow[]>([])
const loading = ref(false)
const error = ref<ApiError | null>(null)

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError('UNKNOWN_ERROR', '请求失败', 0)
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await getArmies()
    armies.value = res.data.items
  } catch (err) {
    error.value = toApiError(err)
  } finally {
    loading.value = false
  }
}

async function copyLink(link: string) {
  try {
    if (!navigator.clipboard) throw new Error('no clipboard')
    await navigator.clipboard.writeText(link)
    ElMessage.success('已复制阵型链接')
  } catch {
    // 非 HTTPS 或旧浏览器没有 clipboard：退化成打开链接，用户可自行复制。
    // 带 noopener：新窗口拿不到 window.opener（链接是第三方域名，别给它回写本页的能力）。
    window.open(link, '_blank', 'noopener')
  }
}

onMounted(load)
</script>

<style scoped>
.army-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.army-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
}

.army-card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.army-card__name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  overflow-wrap: anywhere;
}

.army-card__percentage {
  flex-shrink: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--accent-gold);
}

.army-card__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.army-card__stat dt {
  font-size: 12px;
  color: var(--text-faint);
}

.army-card__stat dd {
  margin: 2px 0 0;
  font-size: 14px;
  color: var(--text-primary);
}

.armies-empty {
  padding: 48px 0;
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
}

.armies-source {
  margin-top: 16px;
}

/* 窄屏单列：两张卡并排时数字会挤成一行放不下 */
@media (max-width: 560px) {
  .army-grid {
    grid-template-columns: 1fr;
  }
}
</style>
