<template>
  <div class="page">
    <section class="page-card">
      <h2 class="page-card__title">查询</h2>
      <p class="page-card__lead">
        输入玩家或部落标签查询档案。支持全角＃、小写、省略 #。
      </p>

      <div class="page-card__toolbar">
        <el-radio-group v-model="kind" class="kind-switch">
          <el-radio-button value="player">玩家</el-radio-button>
          <el-radio-button value="clan">部落</el-radio-button>
        </el-radio-group>

        <TagInput :placeholder="placeholder" class="query-input" @submit="go" />
      </div>

      <div class="quick">
        <span class="quick__label">示例：</span>
        <el-link type="primary" @click="go('#9QJ8L0')">#9QJ8L0（玩家）</el-link>
        <el-link type="primary" @click="go('#2PP', 'clan')">#2PP（部落）</el-link>
      </div>

      <SearchHistory />
      <FavoriteList />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import FavoriteList from '../components/FavoriteList.vue'
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
/* 输入框吃掉操作行的剩余宽度：切到「部落」时长占位文案也不会被截断 */
.query-input {
  flex: 1 1 320px;
  min-width: 240px;
}

.quick {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.quick__label {
  color: var(--text-faint);
  font-size: 0.875rem;
}
</style>
