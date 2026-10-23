<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="app-header__inner">
        <div class="app-header__left">
          <router-link to="/" class="app-brand">
            <span class="app-brand__mark">C</span>
            <span class="app-brand__name">COC 助手</span>
          </router-link>

          <nav aria-label="主导航" class="app-nav">
            <router-link
              v-for="item in NAV_ITEMS"
              :key="item.path"
              :to="item.path"
              class="app-nav__link"
              :class="{ 'app-nav__link--active': isActive(item.path) }"
            >
              {{ item.label }}
            </router-link>
          </nav>
        </div>

        <router-link to="/" class="app-header__search">
          <span class="app-header__search-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor">
              <circle cx="11" cy="11" r="6.5" />
              <path d="m16 16 4 4" stroke-linecap="round" />
            </svg>
          </span>
          <span class="app-header__search-label">搜玩家 / 部落</span>
        </router-link>
      </div>
    </header>

    <main class="app-main">
      <router-view />
    </main>

    <footer class="app-footer">
      <div class="app-footer__inner">
        本站为非官方粉丝站点 · 数据来源：Supercell 官方 API、War Report
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'

const NAV_ITEMS = [
  { path: '/', label: '查询' },
  { path: '/rankings', label: '排行榜' },
  { path: '/armies', label: '阵容' },
  { path: '/bases', label: '阵型' },
]

const route = useRoute()

/** 首页在任何非首页路由下都该高亮吗？不该 —— 它是精确匹配。 */
const isActive = (path: string) =>
  path === '/' ? route.path === '/' : route.path.startsWith(path)
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--surface-page);
}

/* ---- 顶栏 ---- */
.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--surface-page);
  border-bottom: 1px solid var(--border-default);
}
.app-header__inner {
  max-width: var(--page-max);
  margin: 0 auto;
  padding: 0 var(--page-gutter);
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.app-header__left {
  display: flex;
  align-items: center;
  gap: 24px;
  min-width: 0;
}

/* ---- 品牌 ---- */
.app-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: var(--text-primary);
  font-weight: 600;
  font-size: 16px;
  flex-shrink: 0;
}
.app-brand__mark {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: linear-gradient(180deg, var(--accent-gold-bright), var(--accent-gold));
  color: var(--on-accent);
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 15px;
}
.app-brand__name {
  white-space: nowrap;
}

/* ---- 导航 ---- */
.app-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}
.app-nav__link {
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  white-space: nowrap;
  transition: color 0.15s, background 0.15s;
}
.app-nav__link:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}
.app-nav__link--active {
  color: var(--accent-gold);
  background: #e0a0301a;
}

/* ---- 顶栏右侧的搜索入口 ---- */
.app-header__search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  flex-shrink: 0;
  transition: border-color 0.15s, color 0.15s;
}
.app-header__search:hover {
  border-color: var(--accent-gold);
  color: var(--accent-gold);
}
.app-header__search-icon {
  display: grid;
  place-items: center;
}

/* ---- 内容区 ---- */
.app-main {
  flex: 1;
  min-width: 0;
}

/* ---- 页脚 ----
 * 与 header 用同一组 --page-max / --page-gutter，左右边缘才对得上。
 */
.app-footer {
  border-top: 1px solid var(--border-default);
}
.app-footer__inner {
  max-width: var(--page-max);
  margin: 0 auto;
  padding: 16px var(--page-gutter);
  color: var(--text-faint);
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

/* 窄屏：把品牌名与搜索文字藏起来，保住导航项 */
@media (max-width: 720px) {
  .app-brand__name,
  .app-header__search-label {
    display: none;
  }
  .app-header__inner {
    gap: 8px;
  }
}
</style>
