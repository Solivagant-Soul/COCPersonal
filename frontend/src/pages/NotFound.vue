<template>
  <div class="page">
    <h2>页面不存在</h2>
    <p class="page__hint">
      没有与 <code>{{ path }}</code> 对应的页面。
    </p>
    <el-button type="primary" @click="goHome">回到查询</el-button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const path = computed(() => route.fullPath)

function goHome() {
  void router.push({ name: 'query' })
}
</script>
