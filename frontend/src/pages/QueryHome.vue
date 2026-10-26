<template>
  <div class="page">
    <section class="hero">
      <h2 class="hero__title">查询</h2>
      <p class="hero__lead">
        输入玩家或部落标签查询档案。支持全角＃、小写、省略 #。
      </p>

      <el-radio-group v-model="kind" class="hero__switch">
        <el-radio-button value="player">玩家</el-radio-button>
        <el-radio-button value="clan">部落</el-radio-button>
      </el-radio-group>

      <TagInput :placeholder="placeholder" class="hero__input" @submit="go" />

      <div class="quick">
        <span class="quick__label">示例：</span>
        <el-link type="primary" @click="go('#9QJ8L0')">#9QJ8L0（玩家）</el-link>
        <el-link type="primary" @click="go('#2PP', 'clan')">#2PP（部落）</el-link>
      </div>
    </section>

    <SearchHistory class="history" />
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
/* ---- 首屏：像参考站的 hero 一样把搜索框放在视觉中心 ---- */
.hero {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  padding: 38px 34px;
  box-shadow: var(--shadow-card);
}
.hero__title {
  margin: 0 0 8px;
  font-size: 1.875rem;
  font-weight: 700;
  letter-spacing: -0.5px;
}
.hero__lead {
  margin: 0 0 22px;
  color: var(--text-secondary);
  font-size: 0.9375rem;
}
.hero__switch {
  margin-bottom: 14px;
}
.hero__input {
  max-width: 540px;
}

.quick {
  margin-top: 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.quick__label {
  color: var(--text-faint);
  font-size: 0.875rem;
}

.history {
  margin-top: 24px;
}
</style>
