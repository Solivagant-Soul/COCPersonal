<template>
  <div class="page">
    <section class="page-card">
      <div class="bases-head">
        <div>
          <h2 class="page-card__title">阵型</h2>
          <p class="page-card__lead">
            18 本防守阵图集；国际服可直接复制链接，国服需照图手摆。
          </p>
        </div>
        <el-button class="bases-upload" type="primary" @click="uploadOpen = true">
          上传阵型
        </el-button>
      </div>

      <el-radio-group v-model="thLevel" class="bases-filter">
        <el-radio-button
          v-for="opt in LEVEL_OPTIONS"
          :key="opt.value"
          :value="opt.value"
        >
          {{ opt.label }}
        </el-radio-button>
      </el-radio-group>

      <LoadingBlock v-if="loading && !items.length" />
      <ErrorCard v-else-if="error" :error="error" @retry="() => load()" />
      <p v-else-if="!items.length" class="bases-empty">暂无阵型</p>

      <template v-else>
        <ul class="base-grid">
          <li v-for="item in items" :key="item.id" class="base-card">
            <el-image
              v-if="item.imagePath"
              class="base-card__image"
              :src="item.imagePath"
              :preview-src-list="[item.imagePath]"
              fit="cover"
              lazy
            />
            <div v-else class="base-card__image base-card__image--empty">暂无图片</div>

            <div class="base-card__body">
              <div class="base-card__head">
                <h3 class="base-card__title">{{ item.title }}</h3>
                <span v-if="item.thLevel" class="base-card__th">TH{{ item.thLevel }}</span>
              </div>

              <div class="base-card__actions">
                <el-button
                  v-if="item.layoutLink"
                  class="base-card__copy"
                  type="primary"
                  @click="copyLink(item.layoutLink)"
                >
                  复制阵型链接
                </el-button>
                <p v-else class="base-card__note">国服需照图手摆</p>
              </div>

              <p class="base-card__source">
                来源：Ekwaak / Big Legends
                <template v-if="item.sourceUrl">
                  ·
                  <a :href="item.sourceUrl" target="_blank" rel="noopener">原视频</a>
                </template>
              </p>
            </div>
          </li>
        </ul>

        <div v-if="total > items.length" class="bases-more-wrap">
          <el-button class="bases-more" :loading="loading" @click="loadMore">
            加载更多
          </el-button>
        </div>
      </template>
    </section>

    <!-- 署名固定渲染：加载中 / 出错 / 空列表都要有 -->
    <SourceNote />

    <el-dialog v-model="uploadOpen" title="上传阵型" width="560px" destroy-on-close>
      <BaseUploadForm @uploaded="onUploaded" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { getBases, type BaseLayoutItem } from '../api/endpoints'
import { ApiError } from '../api/request'
import BaseUploadForm from '../components/BaseUploadForm.vue'
import ErrorCard from '../components/ErrorCard.vue'
import LoadingBlock from '../components/LoadingBlock.vue'
import SourceNote from '../components/SourceNote.vue'

const PAGE_SIZE = 24

/** 0 = 全部。不用 `null` 当单选值：Element Plus 的 value prop 不声明 null。 */
const LEVEL_OPTIONS = [
  { label: '全部', value: 0 },
  { label: '16 本', value: 16 },
  { label: '17 本', value: 17 },
  { label: '18 本', value: 18 },
] as const

const items = ref<BaseLayoutItem[]>([])
const total = ref(0)
const page = ref(1)
const thLevel = ref(0)
const loading = ref(false)
const error = ref<ApiError | null>(null)
const uploadOpen = ref(false)

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError('UNKNOWN_ERROR', '请求失败', 0)
}

async function load(append = false) {
  loading.value = true
  error.value = null
  try {
    const res = await getBases(
      thLevel.value === 0 ? null : thLevel.value,
      page.value,
      PAGE_SIZE,
    )
    items.value = append ? [...items.value, ...res.data.items] : res.data.items
    total.value = res.data.total
  } catch (err) {
    const apiError = toApiError(err)
    if (append) {
      // 加载更多失败只回退页码，**不能把已加载的卡片换成整页错误**。
      page.value -= 1
      ElMessage.error(apiError.message || '加载更多失败')
    } else {
      error.value = apiError
    }
  } finally {
    loading.value = false
  }
}

function reset() {
  page.value = 1
  items.value = []
  load()
}

watch(thLevel, reset)

function loadMore() {
  page.value += 1
  load(true)
}

function onUploaded() {
  uploadOpen.value = false
  ElMessage.success('已上传')
  reset()
}

async function copyLink(link: string) {
  try {
    if (!navigator.clipboard) throw new Error('no clipboard')
    await navigator.clipboard.writeText(link)
    ElMessage.success('已复制阵型链接')
  } catch {
    // 非 HTTPS 或旧浏览器没有 clipboard：退化成打开链接，用户可自行复制。
    window.open(link, '_blank', 'noopener')
  }
}

onMounted(() => load())
</script>

<style scoped>
.bases-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.bases-head .page-card__lead {
  margin-bottom: 12px;
}

.bases-filter {
  margin-bottom: 20px;
}

.bases-empty {
  margin: 32px 0;
  text-align: center;
  color: var(--text-secondary);
}

.base-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.base-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid var(--surface-subtle);
  background: var(--surface-panel);
}

.base-card__image {
  width: 100%;
  aspect-ratio: 16 / 10;
  background: var(--surface-subtle);
}

.base-card__image--empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 0.875rem;
}

.base-card__body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px 16px;
}

.base-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.base-card__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.base-card__th {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--accent-gold-bright);
  background: color-mix(in srgb, var(--accent-gold) 16%, transparent);
}

.base-card__note {
  margin: 0;
  padding: 6px 0;
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.base-card__source {
  margin: 0;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.base-card__source a {
  color: var(--accent-gold);
}

.bases-more-wrap {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}

@media (max-width: 960px) {
  .base-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .base-grid {
    grid-template-columns: 1fr;
  }
}
</style>
