<template>
  <el-button
    class="follow-btn"
    :class="{ 'follow-btn--on': followed }"
    size="small"
    plain
    :aria-pressed="followed"
    :aria-label="followed ? `取消关注 ${tag}` : `关注 ${tag}`"
    @click="onToggle"
  >
    <span class="follow-btn__star" aria-hidden="true">{{ followed ? '★' : '☆' }}</span>
    {{ followed ? '已关注' : '关注' }}
  </el-button>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import { isFavorite, toggleFavorite, type FavoriteKind } from '../utils/favorites'

/**
 * 关注开关。状态存在 localStorage（见 `utils/favorites`），所以刷新、换页面都还在。
 *
 * 组件不缓存全局状态：`followed` 只在本页有效，路由参数一变就按本地存储重读。
 */
const props = defineProps<{
  tag: string
  kind: FavoriteKind
  name?: string | null
}>()

const emit = defineEmits<{ change: [followed: boolean] }>()

const followed = ref(false)

function refresh() {
  followed.value = isFavorite(props.tag, props.kind)
}

refresh()

// 同一个组件实例在「上一个玩家 → 下一个玩家」之间会被复用，不能只看 props.tag
watch(() => [props.tag, props.kind], refresh)

function onToggle() {
  followed.value = toggleFavorite({
    tag: props.tag,
    kind: props.kind,
    name: props.name ?? null,
  })
  emit('change', followed.value)
}
</script>

<style scoped>
.follow-btn {
  /* 标题是大字号，按钮要贴住基线而不是被拉到与标题同高 */
  align-self: center;
}
/* 已关注只点亮五角星：按钮体保持中性描边，别整颗变金 */
.follow-btn--on .follow-btn__star {
  color: var(--accent-gold-bright);
}
.follow-btn__star {
  margin-right: 4px;
}
</style>
