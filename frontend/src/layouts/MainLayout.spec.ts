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
    { path: '/armies', name: 'armies', component: { template: '<div/>' } },
    { path: '/bases', name: 'bases', component: { template: '<div/>' } },
  ],
})

describe('MainLayout', () => {
  it('导航是查询 / 排行榜 / 阵容 / 阵型四项', () => {
    const w = mount(MainLayout, { global: { plugins: [router] } })
    expect(w.findAll('.app-nav__link').map((a) => a.text())).toEqual([
      '查询',
      '排行榜',
      '阵容',
      '阵型',
    ])
    // 仍未上线的功能不该出现
    expect(w.text()).not.toContain('投稿')
    expect(w.text()).not.toContain('公告')
  })

  it('页脚声明数据来源', () => {
    const w = mount(MainLayout, { global: { plugins: [router] } })
    expect(w.find('footer.app-footer').text()).toContain(
      '数据来源：Supercell 官方 API、War Report',
    )
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
