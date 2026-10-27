import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/request'

vi.mock('../api/endpoints', () => ({
  getClan: vi.fn(),
}))

import { getClan } from '../api/endpoints'
import ClanDetail from './ClanDetail.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/clans/:tag', name: 'clan', component: ClanDetail },
    { path: '/players/:tag', name: 'player', component: { template: '<div/>' } },
  ],
})

async function mountAt(tag = '#2PP') {
  await router.push({ name: 'clan', params: { tag } })
  await router.isReady()
  const w = mount(ClanDetail, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return w
}

const okClan = {
  data: {
    tag: '#2PP',
    name: 'Reddit Zulu',
    clanLevel: 18,
    clanPoints: 55406,
    members: 44,
    description: '我们收活跃玩家',
  },
  meta: { cache: 'HIT', fetchedAt: '2026-01-01T00:00:00Z', ageSeconds: 5, ttlSeconds: 60 },
}

describe('ClanDetail', () => {
  beforeEach(() => {
    vi.mocked(getClan).mockReset()
  })

  it('成功：渲染部落名、标签与缓存状态', async () => {
    vi.mocked(getClan).mockResolvedValue(okClan as never)

    const w = await mountAt()

    expect(w.text()).toContain('Reddit Zulu')
    expect(w.text()).toContain('#2PP')
    expect(w.text()).toContain('HIT')
    expect(w.text()).toContain('我们收活跃玩家')
  })

  it('成功时用统一卡片外壳：一张卡里放标题、标签与数据', async () => {
    vi.mocked(getClan).mockResolvedValue(okClan as never)

    const w = await mountAt()

    expect(w.findAll('.page-card')).toHaveLength(1)
    const card = w.find('.page-card')
    expect(card.find('.page-card__title').text()).toBe('Reddit Zulu')
    expect(card.find('.page-card__lead').text()).toContain('#2PP')
    expect(card.find('.stat-grid').exists()).toBe(true)
    // 不再卡片套卡片
    expect(w.find('.detail-card').exists()).toBe(false)
  })

  it('没名字时标题退回标签', async () => {
    vi.mocked(getClan).mockResolvedValue({
      ...okClan,
      data: { ...okClan.data, name: '' },
    } as never)

    const w = await mountAt()

    expect(w.find('.page-card__title').text()).toBe('#2PP')
  })

  it('出错时标题仍是「部落详情」，错误卡片在卡内', async () => {
    vi.mocked(getClan).mockRejectedValue(
      new ApiError('CLAN_NOT_FOUND', 'clan not found', 404),
    )

    const w = await mountAt()

    expect(w.find('.page-card__title').text()).toBe('部落详情')
    expect(w.find('.page-card .error-card').exists()).toBe(true)
    expect(w.text()).toContain('部落不存在')
  })

  it('STALE：照常渲染并提示「数据可能过期」', async () => {
    vi.mocked(getClan).mockResolvedValue({
      ...okClan,
      meta: { ...okClan.meta, cache: 'STALE' },
    } as never)

    const w = await mountAt()

    expect(w.text()).toContain('Reddit Zulu')
    expect(w.text()).toContain('数据可能过期')
  })
})
