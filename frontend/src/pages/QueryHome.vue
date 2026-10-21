<template>
  <div class="page">
    <h2>查询</h2>
    <p class="page__hint">
      输入玩家或部落标签查询档案。支持全角＃、小写、省略 #。
    </p>

    <el-radio-group v-model="kind" class="kind-switch">
      <el-radio-button value="player">玩家</el-radio-button>
      <el-radio-button value="clan">部落</el-radio-button>
    </el-radio-group>

    <TagInput :placeholder="placeholder" @submit="go" />

    <SearchHistory />

    <div class="quick">
      <span class="quick__label">示例：</span>
      <el-link type="primary" @click="go('#9QJ8L0')">#9QJ8L0（玩家）</el-link>
      <el-link type="primary" @click="go('#2PP', 'clan')">#2PP（部落）</el-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import SearchHistory from '../components/SearchHistory.vue'
import TagInput from '../components/TagInput.vue'
import { addHistory } from '../utils/searchHistory'

const router = useRouter()

/** 查谁。**必须有它才能把查询记进历史** —— 历史条目带类型，
 * 点一下要能直接跳到对应的详情页。 */
const kind = ref<'player' | 'clan'>('player')

const placeholder = computed(() =>
  kind.value === 'clan' ? '输入部落标签，如 #2PP 或 2pp' : '输入玩家标签，如 #8QU8J9J 或 8qu8j9j',
)

function go(tag: string, target: 'player' | 'clan' = kind.value) {
  // 记历史：同样的标签 + 同样的类型再查一次会移到最前，不产生重复
  addHistory(tag, target)
  router.push({ name: target, params: { tag } })
}
</script>

<style scoped>
.kind-switch {
  margin-bottom: 12px;
}
.quick {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.quick__label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
