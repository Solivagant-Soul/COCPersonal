<template>
  <span class="army-unit" :title="`${unit.name} ×${unit.count}`">
    <img
      v-if="!failed"
      class="army-unit__image"
      :src="src"
      :alt="unit.name"
      loading="lazy"
      decoding="async"
      @error="onError"
    />
    <span v-else class="army-unit__fallback" :class="`army-unit__fallback--${unit.kind}`">
      {{ fallbackText }}
    </span>

    <!-- 装备图动辄几 MB，预览里不展示；详情里也不需要角标 -->
    <span v-if="showCount && unit.count > 0" class="army-unit__count">
      {{ unit.count }}
    </span>
  </span>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { UNIT_IMAGE_FOLDER, type ArmyUnit } from '../data/armyComposition'

const props = withDefaults(
  defineProps<{
    unit: ArmyUnit
    showCount?: boolean
  }>(),
  { showCount: true },
)

/** 服务器上的图可能是 png / jpg / webp（下载脚本按文件头纠正过扩展名）。 */
const EXTENSIONS = ['png', 'jpg', 'webp'] as const

const extIndex = ref(0)
const failed = ref(false)

const src = computed(() => {
  const folder = UNIT_IMAGE_FOLDER[props.unit.kind]
  return `/pictures/${folder}/${encodeURIComponent(props.unit.name)}.${EXTENSIONS[extIndex.value]}`
})

const fallbackText = computed(() => {
  // 缺图时给个短标签：全名放 title 里，不挤爆 44px 的格子
  return props.unit.name.replace(/^(超级|戈仑|英雄|守护者|烈焰|寒冰)/, '').slice(0, 2)
})

function onError() {
  if (extIndex.value < EXTENSIONS.length - 1) {
    extIndex.value += 1
    return
  }
  failed.value = true
}

// 列表里同一种组件复用同一个实例时，换 unit 要重置图片探测状态
watch(
  () => props.unit,
  () => {
    extIndex.value = 0
    failed.value = false
  },
)
</script>

<style scoped>
.army-unit {
  position: relative;
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border: 1px solid var(--border-default);
  border-radius: 9px;
  background: var(--surface-subtle);
}

.army-unit__image {
  width: 100%;
  height: 100%;
  padding: 3px;
  object-fit: contain;
}

.army-unit__fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border-radius: 8px;
  background: #3a3a3c;
  color: var(--text-secondary);
  font-size: 0.75rem;
  line-height: 1.1;
  text-align: center;
  overflow: hidden;
}

.army-unit__fallback--spell {
  background: #2d2440;
  color: #c9b8f5;
}

.army-unit__fallback--hero {
  background: #3a2a16;
  color: var(--accent-gold-bright);
}

.army-unit__fallback--pet {
  background: #16302c;
  color: #7fe3d8;
}

.army-unit__fallback--siege {
  background: #33251b;
  color: #e6b58c;
}

.army-unit__count {
  position: absolute;
  right: 1px;
  bottom: 1px;
  min-width: 15px;
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
