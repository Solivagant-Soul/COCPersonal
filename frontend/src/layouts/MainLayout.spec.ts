import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import MainLayout from './MainLayout.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'query', component: { template: '<div/>' } },
    { path: '/rankings', name: 'rankings', component: { template: '<div/>' } },
    { path: '/players/:tag', name: 'player', component: { template: '<div/>' } },
  ],
})

describe('MainLayout', () => {
  it('导航只含查询与排行榜', () => {
    const w = mount(MainLayout, { global: { plugins: [router] } })
    const text = w.text()
    expect(text).toContain('查询')
    expect(text).toContain('排行榜')
    expect(text).not.toContain('投稿')
    expect(text).not.toContain('公告')
  })

  it('用顶部导航（不再是左侧边栏）', () => {
    const w = mount(MainLayout, { global: { plugins: [router] } })
    expect(w.find('header.app-header').exists()).toBe(true)
    expect(w.find('.app-nav').exists()).toBe(true)
    // 旧的侧边栏结构不该还在
    expect(w.find('aside.app-aside').exists()).toBe(false)
  })

  it('当前路由的导航项高亮', async () => {
    const w = mount(MainLayout, { global: { plugins: [router] } })
    await router.push('/rankings')
    await router.isReady()
    await w.vm.$nextTick()

    const active = w.findAll('.app-nav__link--active')
    expect(active).toHaveLength(1)
    expect(active[0].text()).toBe('排行榜')
  })

  it('详情页不点亮任何导航项', async () => {
    const w = mount(MainLayout, { global: { plugins: [router] } })
    await router.push('/players/%23ABC')
    await router.isReady()
    await w.vm.$nextTick()

    // 首页是精确匹配 —— 详情页下不该把「查询」点亮
    expect(w.findAll('.app-nav__link--active')).toHaveLength(0)
  })
})
