import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({
  GLOBAL_LOCATION_ID: 32000000,
  getRankings: vi.fn(),
}))

import { getRankings } from '../api/endpoints'
import Rankings from './Rankings.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/rankings', name: 'rankings', component: Rankings },
    { path: '/players/:tag', name: 'player', component: { template: '<div/>' } },
    { path: '/clans/:tag', name: 'clan', component: { template: '<div/>' } },
  ],
})

const clanRow = {
  rank: 1,
  tag: '#2PP',
  name: 'Reddit Zulu',
  points: 55406,
  members: 44,
  clanLevel: 18,
}

const rankingsPage = {
  data: { items: [clanRow], total: 1, kind: 'clans' },
  meta: {
    cache: 'HIT',
    fetchedAt: '2026-01-01T00:00:00Z',
    ageSeconds: 10,
    ttlSeconds: 21600,
  },
}

async function mountRankings() {
  await router.push({ name: 'rankings' })
  await router.isReady()
  const w = mount(Rankings, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return w
}

describe('Rankings', () => {
  beforeEach(() => {
    vi.mocked(getRankings).mockReset()
    vi.mocked(getRankings).mockResolvedValue(rankingsPage as never)
  })

  it('固定查全服（32000000），不再有地区选择器', async () => {
    const w = await mountRankings()

    expect(getRankings).toHaveBeenCalledWith('clans', 32000000, 1, 20)
    expect(w.text()).toContain('Reddit Zulu')
    // 地区下拉框已经拿掉。
    // **不能**断言没有 el-select —— el-pagination 的 layout 含 sizes，
    // 它自己就渲染一个页长选择器。断言「没有地区选项」才对。
    expect(w.text()).not.toContain('选择地区')
    expect(w.find('.toolbar__select').exists()).toBe(false)
  })

  it('只提供部落与玩家两个榜种', async () => {
    const w = await mountRankings()

    const labels = w.findAll('.el-radio-button__inner').map((b) => b.text())
    expect(labels).toEqual(['部落', '玩家'])
    // 已移除的三类榜不该再出现在选项里
    expect(w.text()).not.toContain('都城')
    expect(w.text()).not.toContain('基地')
  })

  it('切换榜单类型触发重新拉取', async () => {
    const w = await mountRankings()
    vi.mocked(getRankings).mockClear()

    const group = w.findComponent({ name: 'ElRadioGroup' })
    await group.setValue('players')
    await flushPromises()

    expect(getRankings).toHaveBeenCalledWith('players', 32000000, 1, 20)
  })

  it('空 items 显示「暂无数据」空态，不是错误', async () => {
    vi.mocked(getRankings).mockResolvedValue({
      data: { items: [], total: 0, kind: 'clans' },
      meta: rankingsPage.meta,
    } as never)

    const w = await mountRankings()

    expect(w.text()).toContain('暂无数据')
    expect(w.text()).not.toContain('查询失败')
  })

  it('page_size 传 100（>50）不报错，按后端返回渲染', async () => {
    const w = await mountRankings()
    vi.mocked(getRankings).mockClear()

    const pager = w.findComponent({ name: 'ElPagination' })
    // 真实 el-pagination 改页长时会同时发这两个事件
    await pager.vm.$emit('update:page-size', 100)
    await pager.vm.$emit('size-change', 100)
    await flushPromises()

    expect(getRankings).toHaveBeenCalledWith('clans', 32000000, 1, 100)
    expect(w.text()).toContain('Reddit Zulu')
    expect(w.text()).not.toContain('查询失败')
  })
})
