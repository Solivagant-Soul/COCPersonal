<template>
  <el-container class="app-shell">
    <el-aside width="220px" class="app-aside">
      <div class="app-brand">COC 助手</div>
      <el-menu :default-active="activePath" router class="app-menu">
        <el-menu-item index="/">查询</el-menu-item>
        <el-menu-item index="/rankings">排行榜</el-menu-item>
      </el-menu>
    </el-aside>
    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activePath = computed(() => route.path)
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
}
.app-aside {
  background: #fff;
  border-right: 1px solid #ebeef5;
}
.app-brand {
  padding: 18px 20px;
  font-size: 18px;
  font-weight: 600;
}
.app-menu {
  border-right: none;
}
.app-main {
  background: #f5f6f8;
}
</style>
