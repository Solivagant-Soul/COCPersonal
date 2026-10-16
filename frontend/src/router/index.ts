import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'query',
      component: () => import('../pages/QueryHome.vue'),
    },
    {
      path: '/players/:tag',
      name: 'player',
      component: () => import('../pages/PlayerDetail.vue'),
    },
    {
      path: '/clans/:tag',
      name: 'clan',
      component: () => import('../pages/ClanDetail.vue'),
    },
    {
      path: '/rankings',
      name: 'rankings',
      component: () => import('../pages/Rankings.vue'),
    },
  ],
})

export default router
