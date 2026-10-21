import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { readHistory } from '../utils/searchHistory'
import QueryHome from './QueryHome.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'query', component: QueryHome },
    { path: '/players/:tag', name: 'player', component: { template: '<div/>' } },
    { path: '/clans/:tag', name: 'clan', component: { template: '<div/>' } },
  ],
})

function mountPage() {
  return mount(QueryHome, { global: { plugins: [router, ElementPlus] } })
}

/**
 * 「查询」按钮。**不能**用 `find('button')` —— el-radio-button 也渲染成
 * `<button>`，find 会抓到切换器的按钮而不是查询按钮。
 */
function queryButton(w: ReturnType<typeof mountPage>) {
  return w.findAll('button').find((b) => b.text() === '查询')!
}

/**
 * 标签输入框。**不能**用 `find('input')` —— el-radio-group 会在页面上渲染
 * 一批隐藏的 radio input，find 抓到的是第一个（即切换器的），不是输入框。
 */
function tagInput(w: ReturnType<typeof mountPage>) {
  return w.find('input[type="text"]')
}

describe('QueryHome 搜索历史', () => {
  beforeEach(() => {
    localStorage.clear()
    router.push('/')
  })

  it('查询后把标签与类型记进历史', async () => {
    const w = mountPage()
    await tagInput(w).setValue('8qu8j9j')
    await queryButton(w).trigger('click')
    await flushPromises()

    const history = readHistory()
    expect(history).toHaveLength(1)
    expect(history[0].tag).toBe('#8QU8J9J')
    expect(history[0].kind).toBe('player')
  })

  it('切到部落后查询，历史记为部落', async () => {
    const w = mountPage()
    // 切到「部落」。**操作隐藏的 radio input**，不是 `.el-radio-button__inner`
    // —— 后者是纯展示层，点击它不会改 v-model。
    await w.findAll('.el-radio-button__original-radio')[1].setValue(true)

    await tagInput(w).setValue('2pp')
    await queryButton(w).trigger('click')
    await flushPromises()

    const history = readHistory()
    expect(history).toHaveLength(1)
    expect(history[0].tag).toBe('#2PP')
    expect(history[0].kind).toBe('clan')
  })

  it('历史条目渲染出来，点一下跳到对应详情页', async () => {
    localStorage.setItem(
      'cocpersonal.searchHistory',
      JSON.stringify([
        { tag: '#AAA', kind: 'player', at: 2 },
        { tag: '#BBB', kind: 'clan', at: 1 },
      ]),
    )

    const w = mountPage()
    await flushPromises()

    const links = w.findAll('.history__link')
    expect(links).toHaveLength(2)
    // 最新的在前
    expect(links[0].text()).toContain('#AAA')

    await links[1].trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('clan')
    expect(router.currentRoute.value.params.tag).toBe('#BBB')
  })

  it('能删掉单条历史', async () => {
    localStorage.setItem(
      'cocpersonal.searchHistory',
      JSON.stringify([
        { tag: '#AAA', kind: 'player', at: 2 },
        { tag: '#BBB', kind: 'clan', at: 1 },
      ]),
    )

    const w = mountPage()
    await flushPromises()

    await w.findAll('.history__remove')[0].trigger('click')
    await flushPromises()

    expect(readHistory().map((e) => e.tag)).toEqual(['#BBB'])
  })

  it('没有历史时不渲染历史区块', () => {
    const w = mountPage()
    expect(w.find('.history').exists()).toBe(false)
  })
})
