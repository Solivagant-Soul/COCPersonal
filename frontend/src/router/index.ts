import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

/** 浏览器标签页标题的基名；各路由用 `meta.title` 补前缀。 */
export const APP_TITLE = 'COC 助手'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'query',
    component: () => import('../pages/QueryHome.vue'),
    meta: { title: '查询' },
  },
  {
    path: '/players/:tag',
    name: 'player',
    component: () => import('../pages/PlayerDetail.vue'),
    meta: { title: '玩家详情' },
  },
  {
    path: '/clans/:tag',
    name: 'clan',
    component: () => import('../pages/ClanDetail.vue'),
    meta: { title: '部落详情' },
  },
  {
    path: '/rankings',
    name: 'rankings',
    component: () => import('../pages/Rankings.vue'),
    meta: { title: '排行榜' },
  },
  {
    // 兜底：不存在的地址给一个「能回去」的页面，而不是空的 router-view。
    // SPA 里用户手改地址或点旧链接进来时很常见，空屏会让人以为是坏了。
    path: '/:pathMatch(.*)*',
    name: 'notFound',
    component: () => import('../pages/NotFound.vue'),
    meta: { title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  // 换页回到顶部：从长列表点进详情时，停在页面底部会让人以为没跳转。
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `${title} · ${APP_TITLE}` : APP_TITLE
})

export default router
