<template>
  <span class="unit-tile" :class="{ 'unit-tile--max': isMax }" :title="title">
    <img
      v-if="asset && !failed"
      class="unit-tile__image"
      :src="src"
      :alt="asset.zh"
      loading="lazy"
      decoding="async"
      @error="onError"
    />
    <span v-else class="unit-tile__fallback">{{ fallbackText }}</span>

    <span v-if="level !== null" class="unit-tile__level">{{ level }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { UnitAsset } from '../data/unitAssets'

/**
 * 一个兵种 / 法术 / 英雄格子：本地素材图 + 右下角等级。
 *
 * 图可能被下载脚本按文件头纠正过扩展名（png / jpg / webp），所以按顺序探测，
 * 全失败才退化成文字 —— 与 `ArmyUnitIcon` 同一套约定。
 */
const props = withDefaults(
  defineProps<{
    asset: UnitAsset | null
    /** 上游英文名，素材缺失时用于兜底显示。 */
    name: string
    level?: number | null
    maxLevel?: number | null
  }>(),
  { level: null, maxLevel: null },
)

const EXTENSIONS = ['png', 'jpg', 'webp'] as const

const extIndex = ref(0)
const failed = ref(false)

const src = computed(() => {
  if (!props.asset) return ''
  return `/pictures/${props.asset.folder}/${encodeURIComponent(props.asset.zh)}.${EXTENSIONS[extIndex.value]}`
})

const level = computed(() => (typeof props.level === 'number' ? props.level : null))

const isMax = computed(
  () => level.value !== null && typeof props.maxLevel === 'number' && level.value >= props.maxLevel,
)

const title = computed(() => {
  const label = props.asset?.zh ?? props.name
  return level.value === null ? label : `${label} Lv.${level.value}/${props.maxLevel ?? '?'}`
})

const fallbackText = computed(() => {
  // 有中文名时取前两个字；没有就退英文前两个字符，至少占位不空
  return (props.asset?.zh ?? props.name).slice(0, 2)
})

function onError() {
  if (extIndex.value < EXTENSIONS.length - 1) {
    extIndex.value += 1
    return
  }
  failed.value = true
}

// 同一个组件实例被复用（列表重排）时，换单位要重置图片探测状态
watch(
  () => props.asset,
  () => {
    extIndex.value = 0
    failed.value = false
  },
)
</script>

<style scoped>
.unit-tile {
  position: relative;
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border: 1px solid var(--border-default);
  border-radius: 10px;
  background: var(--surface-subtle);
}

/* 满级：金色描边，一眼能看出"这个已经练满了" */
.unit-tile--max {
  border-color: var(--accent-gold);
  box-shadow: inset 0 0 0 1px var(--accent-gold-dim, #7a6420);
}

.unit-tile__image {
  width: 100%;
  height: 100%;
  padding: 3px;
  object-fit: contain;
}

.unit-tile__fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border-radius: 9px;
  background: #3a3a3c;
  color: var(--text-secondary);
  font-size: 0.75rem;
  line-height: 1.1;
  text-align: center;
  overflow: hidden;
}

.unit-tile__level {
  position: absolute;
  right: 1px;
  bottom: 1px;
  min-width: 16px;
  padding: 0 3px;
  border-radius: 5px;
  background: #000000c4;
  color: var(--accent-gold-bright);
  font-size: 0.6875rem;
  font-weight: 600;
  line-height: 15px;
  text-align: center;
}
</style>
