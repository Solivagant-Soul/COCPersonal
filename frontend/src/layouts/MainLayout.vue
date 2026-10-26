<template>
  <div class="app-shell">
    <!-- 左侧一级导航：品牌 / 四个页签 / 底部设置 -->
    <aside class="app-aside" aria-label="侧边栏">
      <router-link to="/" class="app-brand">
        <img class="app-brand__icon" :src="brandIcon" alt="COC部落营地图标" />
        <span class="app-brand__name">COC部落营地</span>
      </router-link>

      <nav aria-label="主导航" class="app-nav">
        <router-link
          v-for="item in NAV_ITEMS"
          :key="item.path"
          :to="item.path"
          class="app-nav__link"
          :class="{ 'app-nav__link--active': isActive(item.path) }"
          :title="item.label"
        >
          <svg
            class="app-nav__icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path :d="item.icon" />
          </svg>
          <span class="app-nav__label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="app-aside__bottom">
        <button
          type="button"
          class="app-settings"
          title="设置"
          :aria-expanded="settingsOpen ? 'true' : 'false'"
          aria-controls="settings-drawer"
          @click="settingsOpen = true"
        >
          <svg
            class="app-settings__icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
            <circle cx="15" cy="7" r="2.2" />
            <circle cx="9" cy="17" r="2.2" />
          </svg>
          <span class="app-settings__label">设置</span>
        </button>
      </div>
    </aside>

    <div class="app-body">
      <!-- 窄屏才有：品牌 + 导航抽屉入口 -->
      <header class="app-topbar">
        <button
          type="button"
          class="app-menu-toggle"
          aria-label="打开导航"
          @click="mobileNavOpen = true"
        >
          <svg
            viewBox="0 0 24 24"
            width="22"
            height="22"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </button>
        <router-link to="/" class="app-brand app-brand--compact">
          <img class="app-brand__icon" :src="brandIcon" alt="COC部落营地图标" />
          <span class="app-brand__name">COC部落营地</span>
        </router-link>
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

    <el-drawer
      id="settings-drawer"
      v-model="settingsOpen"
      title="设置"
      direction="rtl"
      size="380px"
      class="settings-drawer"
    >
      <section class="settings-group">
        <h3 class="settings-group__title">界面字号</h3>
        <el-radio-group v-model="uiScale">
          <el-radio-button value="standard">标准</el-radio-button>
          <el-radio-button value="large">大</el-radio-button>
        </el-radio-group>
        <p class="settings-group__hint">选择「大」会放大全站文字，并记住这次选择。</p>
      </section>

      <section class="settings-group">
        <h3 class="settings-group__title">关于本站</h3>
        <p class="settings-group__text">
          COC部落营地是非官方粉丝站点，提供玩家 / 部落查询、排行榜与阵容数据。
        </p>
        <p class="settings-group__text">
          数据来源：Supercell 官方 API、
          <a href="https://warreport.app" target="_blank" rel="noopener">War Report</a>。
        </p>
      </section>

      <section class="settings-group">
        <h3 class="settings-group__title">管理</h3>
        <a class="settings-group__link" href="/admin" target="_blank" rel="noopener">
          进入管理后台
        </a>
      </section>
    </el-drawer>

    <el-drawer
      v-model="mobileNavOpen"
      title="导航"
      direction="ltr"
      size="280px"
      class="mobile-nav-drawer"
    >
      <nav class="mobile-nav" aria-label="移动端主导航">
        <router-link
          v-for="item in NAV_ITEMS"
          :key="item.path"
          :to="item.path"
          class="app-nav__link"
          :class="{ 'app-nav__link--active': isActive(item.path) }"
          @click="mobileNavOpen = false"
        >
          <svg
            class="app-nav__icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path :d="item.icon" />
          </svg>
          <span class="app-nav__label">{{ item.label }}</span>
        </router-link>

        <button type="button" class="app-settings" @click="openSettingsFromMobile">
          <svg
            class="app-settings__icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
            <circle cx="15" cy="7" r="2.2" />
            <circle cx="9" cy="17" r="2.2" />
          </svg>
          <span class="app-settings__label">设置</span>
        </button>
      </nav>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import brandIcon from '../assets/brand-icon.jpeg'

/** 一级页签。图标是 24×24 线性 SVG 的 path，避免为四个图标再引一套图标库。 */
const NAV_ITEMS = [
  {
    path: '/',
    label: '查询',
    icon: 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13Zm5-1.5 4.5 4.5',
  },
  { path: '/rankings', label: '排行榜', icon: 'M5 20v-8M12 20V4M19 20v-5' },
  {
    path: '/armies',
    label: '阵容',
    icon: 'M8.5 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm7 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2.5 20c0-3 2.6-5 6-5s6 2 6 5M14.5 15.2c2.7.3 4.5 2.2 4.5 4.8',
  },
  { path: '/bases', label: '阵型', icon: 'M12 3l7 2.7v5.6c0 4.2-2.8 7.7-7 9.7-4.2-2-7-5.5-7-9.7V5.7L12 3Z' },
]

const UI_SCALE_KEY = 'coc-ui-scale'
type UiScale = 'standard' | 'large'

function readScale(): UiScale {
  try {
    return localStorage.getItem(UI_SCALE_KEY) === 'large' ? 'large' : 'standard'
  } catch {
    // 隐私模式下 localStorage 可能直接抛异常：退回标准字号，不阻断页面。
    return 'standard'
  }
}

const route = useRoute()
const settingsOpen = ref(false)
const mobileNavOpen = ref(false)
const uiScale = ref<UiScale>(readScale())

/** 首页是精确匹配；其余页签匹配子路由（详情页属于查询，但不高亮）。 */
const isActive = (path: string) =>
  path === '/' ? route.path === '/' : route.path.startsWith(path)

function applyScale(value: UiScale) {
  document.documentElement.dataset.uiScale = value
}

watch(uiScale, (value) => {
  applyScale(value)
  try {
    localStorage.setItem(UI_SCALE_KEY, value)
  } catch {
    // 存不了就只在本次会话生效，不影响使用。
  }
})

onMounted(() => applyScale(uiScale.value))

function openSettingsFromMobile() {
  mobileNavOpen.value = false
  settingsOpen.value = true
}
</script>

<style scoped>
/* ---------------------------------------------------------------- 外壳 */
.app-shell {
  min-height: 100vh;
  display: flex;
  background: var(--surface-page);
}

/* ---------------------------------------------------------------- 侧边栏 */
.app-aside {
  position: sticky;
  top: 0;
  z-index: 100;
  width: 248px;
  height: 100vh;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 22px 16px 18px;
  background: var(--surface-panel);
  border-right: 1px solid var(--border-default);
}

/* ---------------------------------------------------------------- 品牌 */
.app-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 8px 22px;
  text-decoration: none;
  color: var(--text-primary);
  flex-shrink: 0;
}
.app-brand__icon {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  object-fit: cover;
  box-shadow:
    0 0 0 1px #ffffff1a,
    0 8px 20px #00000059;
  flex-shrink: 0;
}
.app-brand__name {
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--accent-gold);
  white-space: nowrap;
}

/* ---------------------------------------------------------------- 导航 */
.app-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.app-nav__link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.9375rem;
  white-space: nowrap;
  transition:
    color 0.15s,
    background 0.15s;
}
.app-nav__link:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}
.app-nav__link--active {
  color: var(--accent-gold);
  background: #e0a0301a;
}
/* 选中项左侧的金色竖条：比只换颜色更容易一眼定位 */
.app-nav__link--active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 3px;
  height: 18px;
  border-radius: 2px;
  background: var(--accent-gold);
  transform: translateY(-50%);
}
.app-nav__icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

/* ---------------------------------------------------------------- 底部设置 */
.app-aside__bottom {
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid var(--border-default);
}
.app-settings {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 0.9375rem;
  text-align: left;
  cursor: pointer;
  transition:
    color 0.15s,
    background 0.15s;
}
.app-settings:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}
.app-settings__icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

/* ---------------------------------------------------------------- 内容区 */
.app-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.app-main {
  flex: 1;
  min-width: 0;
}

/* 顶部栏只在窄屏出现 */
.app-topbar {
  display: none;
  position: sticky;
  top: 0;
  z-index: 90;
  align-items: center;
  gap: 12px;
  padding: 10px var(--page-gutter);
  background: var(--surface-page);
  border-bottom: 1px solid var(--border-default);
}
.app-menu-toggle {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-panel);
  color: var(--text-primary);
  cursor: pointer;
}
.app-menu-toggle:hover {
  border-color: var(--accent-gold);
  color: var(--accent-gold);
}
.app-brand--compact {
  padding: 0;
  gap: 10px;
}
.app-brand--compact .app-brand__icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
}

/* ---------------------------------------------------------------- 页脚 */
.app-footer {
  border-top: 1px solid var(--border-default);
}
.app-footer__inner {
  max-width: var(--page-max);
  margin: 0 auto;
  padding: 18px var(--page-gutter);
  color: var(--text-faint);
  font-size: 0.8125rem;
  line-height: 1.6;
  text-align: center;
}

/* ---------------------------------------------------------------- 设置抽屉 */
.settings-group + .settings-group {
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid var(--border-default);
}
.settings-group__title {
  margin: 0 0 12px;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.settings-group__hint,
.settings-group__text {
  margin: 12px 0 0;
  color: var(--text-secondary);
  font-size: 0.875rem;
  line-height: 1.7;
}
.settings-group__link {
  display: inline-flex;
  align-items: center;
  padding: 9px 16px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--accent-gold);
  font-size: 0.9375rem;
  text-decoration: none;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.settings-group__link:hover {
  border-color: var(--accent-gold);
  background: #e0a03014;
}

/* 移动端导航抽屉 */
.mobile-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mobile-nav .app-settings {
  margin-top: 12px;
  border-top: 1px solid var(--border-default);
  border-radius: 0;
  padding-top: 16px;
}

/* 设置抽屉在手机上不能超过屏幕宽度 */
:deep(.el-drawer.settings-drawer) {
  max-width: 92vw;
}

/* ---------------------------------------------------------------- 窄屏 */
/* 1024px 以下：侧边栏收成图标条，保住内容宽度 */
@media (max-width: 1024px) {
  .app-aside {
    width: 76px;
    padding: 18px 10px 14px;
    align-items: center;
  }
  .app-brand {
    padding: 0 0 18px;
  }
  .app-brand__name,
  .app-nav__label,
  .app-settings__label {
    display: none;
  }
  .app-nav {
    width: 100%;
  }
  .app-nav__link,
  .app-settings {
    justify-content: center;
    padding: 12px 0;
  }

  /* 抽屉里的导航是完整版：图标条那套「只留图标」不能带进来 */
  .mobile-nav .app-nav__label,
  .mobile-nav .app-settings__label {
    display: inline;
  }
  .mobile-nav .app-nav__link,
  .mobile-nav .app-settings {
    justify-content: flex-start;
    padding: 11px 14px;
  }
}

/* 720px 以下：侧边栏整体收进抽屉，顶部只留品牌与菜单按钮 */
@media (max-width: 720px) {
  .app-aside {
    display: none;
  }
  .app-topbar {
    display: flex;
  }
  /* 顶部栏的品牌必须带文字：这是页面上唯一的站名 */
  .app-brand--compact .app-brand__name {
    display: inline;
  }
}
</style>
