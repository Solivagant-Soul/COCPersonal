import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({
  getLocations: vi.fn(),
  getRankings: vi.fn(),
}))

import { getLocations, getRankings } from '../api/endpoints'
import Rankings from './Rankings.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/rankings', name: 'rankings', component: Rankings },
    { path: '/players/:tag', name: 'player', component: { template: '<div/>' } },
    { path: '/clans/:tag', name: 'clan', component: { template: '<div/>' } },
  ],
})

const locations = {
  data: {
    items: [
      { id: 32000010, name: 'Bosnia and Herzegovina', countryCode: 'BA' },
      { id: 32000001, name: 'China', countryCode: 'CN' },
    ],
    total: 2,
  },
  meta: { cache: 'MISS', fetchedAt: null, ageSeconds: null, ttlSeconds: 21600 },
}

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
    vi.mocked(getLocations).mockReset()
    vi.mocked(getRankings).mockReset()
    vi.mocked(getLocations).mockResolvedValue(locations as never)
    vi.mocked(getRankings).mockResolvedValue(rankingsPage as never)
  })

  it('初始加载地区，默认选中夹具里的国家地区 China(32000001)', async () => {
    const w = await mountRankings()

    expect(getLocations).toHaveBeenCalled()
    expect(getRankings).toHaveBeenCalledWith('clans', 32000001, 1, 20)
    expect(w.text()).toContain('China')
    expect(w.text()).toContain('Reddit Zulu')
  })

  it('切换榜单类型触发重新拉取', async () => {
    const w = await mountRankings()
    vi.mocked(getRankings).mockClear()

    const group = w.findComponent({ name: 'ElRadioGroup' })
    await group.setValue('players')
    await flushPromises()

    expect(getRankings).toHaveBeenCalledWith('players', 32000001, 1, 20)
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

    expect(getRankings).toHaveBeenCalledWith('clans', 32000001, 1, 100)
    expect(w.text()).toContain('Reddit Zulu')
    expect(w.text()).not.toContain('查询失败')
  })
})
