import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { installElementPlus } from '../plugins/element'
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

function mountLayout() {
  return mount(MainLayout, {
    attachTo: document.body,
    global: { plugins: [router, { install: installElementPlus }] },
  })
}

beforeEach(() => {
  localStorage.clear()
  delete document.documentElement.dataset.uiScale
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('MainLayout', () => {
  it('左上角是图标 + 「COC部落营地」文字', () => {
    const w = mountLayout()
    const brand = w.find('.app-brand')
    expect(brand.text()).toContain('COC部落营地')
    expect(brand.find('img.app-brand__icon').exists()).toBe(true)
  })

  it('一级导航是查询 / 排行榜 / 阵容 / 阵型四项', () => {
    const w = mountLayout()
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

  it('用左侧边栏，不再有顶部导航栏', () => {
    const w = mountLayout()
    expect(w.find('aside.app-aside').exists()).toBe(true)
    expect(w.find('header.app-header').exists()).toBe(false)
  })

  it('设置入口在侧边栏底部，点击打开设置抽屉', async () => {
    const w = mountLayout()
    const button = w.find('.app-aside__bottom .app-settings')
    expect(button.exists()).toBe(true)
    expect(button.text()).toContain('设置')
    expect(button.attributes('aria-expanded')).toBe('false')

    await button.trigger('click')
    await flushPromises()

    expect(button.attributes('aria-expanded')).toBe('true')
    expect(document.body.textContent).toContain('界面字号')
    expect(document.body.textContent).toContain('关于本站')
    expect(document.body.textContent).toContain('管理后台')
  })

  it('字号选「大」会放大全站文字并记住选择', async () => {
    const w = mountLayout()
    await w.find('.app-settings').trigger('click')
    await flushPromises()

    const large = Array.from(document.body.querySelectorAll<HTMLElement>('.el-radio-button')).find(
      (el) => el.textContent?.trim() === '大',
    )
    expect(large).toBeTruthy()
    large!.click()
    await flushPromises()

    expect(document.documentElement.dataset.uiScale).toBe('large')
    expect(localStorage.getItem('coc-ui-scale')).toBe('large')
  })

  it('下次打开时沿用记住的字号', () => {
    localStorage.setItem('coc-ui-scale', 'large')
    mountLayout()
    expect(document.documentElement.dataset.uiScale).toBe('large')
  })

  it('页脚声明数据来源', () => {
    const w = mountLayout()
    expect(w.find('footer.app-footer').text()).toContain(
      '数据来源：Supercell 官方 API、War Report',
    )
  })

  it('当前路由的导航项高亮', async () => {
    const w = mountLayout()
    await router.push('/rankings')
    await router.isReady()
    await w.vm.$nextTick()

    const active = w.findAll('.app-nav__link--active')
    expect(active).toHaveLength(1)
    expect(active[0].text()).toBe('排行榜')
  })

  it('详情页不点亮任何导航项', async () => {
    const w = mountLayout()
    await router.push('/players/%23ABC')
    await router.isReady()
    await w.vm.$nextTick()

    // 首页是精确匹配 —— 详情页下不该把「查询」点亮
    expect(w.findAll('.app-nav__link--active')).toHaveLength(0)
  })

  it('窄屏用菜单按钮打开抽屉式导航', async () => {
    const w = mountLayout()
    const toggle = w.find('.app-menu-toggle')
    expect(toggle.exists()).toBe(true)

    await toggle.trigger('click')
    await flushPromises()

    const drawer = document.body.querySelector('.mobile-nav')
    expect(drawer).toBeTruthy()
    expect(drawer?.textContent).toContain('排行榜')
  })
})
