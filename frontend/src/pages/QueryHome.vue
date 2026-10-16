<template>
  <div class="page">
    <h2>查询</h2>
    <p class="page__hint">
      输入玩家标签查询档案（支持全角＃、小写、省略 #）。部落标签可把
      <code>/players/xxx</code> 手动改成 <code>/clans/xxx</code>。
    </p>

    <TagInput @submit="go" />

    <div class="quick">
      <span class="quick__label">示例：</span>
      <el-link type="primary" @click="go('#9QJ8L0')">#9QJ8L0（玩家）</el-link>
      <el-link type="primary" @click="go('#2PP', 'clan')">#2PP（部落）</el-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

import TagInput from '../components/TagInput.vue'

const router = useRouter()

function go(tag: string, name: 'player' | 'clan' = 'player') {
  router.push({ name, params: { tag } })
}
</script>

<style scoped>
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
