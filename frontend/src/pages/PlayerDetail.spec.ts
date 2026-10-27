import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/request'

vi.mock('../api/endpoints', () => ({
  getPlayer: vi.fn(),
}))

import { getPlayer } from '../api/endpoints'
import PlayerDetail from './PlayerDetail.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/players/:tag', name: 'player', component: PlayerDetail },
    { path: '/clans/:tag', name: 'clan', component: { template: '<div/>' } },
  ],
})

async function mountAt(tag = '#9QJ8L0') {
  await router.push({ name: 'player', params: { tag } })
  await router.isReady()
  const w = mount(PlayerDetail, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return w
}

const okPlayer = {
  data: { tag: '#9QJ8L0', name: 'Vasilije', expLevel: 205, trophies: 4902 },
  meta: { cache: 'HIT', fetchedAt: '2026-01-01T00:00:00Z', ageSeconds: 5, ttlSeconds: 60 },
}

describe('PlayerDetail', () => {
  beforeEach(() => {
    vi.mocked(getPlayer).mockReset()
  })

  it('成功：渲染 name/tag，并带上 meta.cache', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)

    const w = await mountAt()

    expect(w.text()).toContain('Vasilije')
    expect(w.text()).toContain('#9QJ8L0')
    expect(w.text()).toContain('HIT')
  })

  it('STALE：照常渲染档案并提示「数据可能过期」，不当成错误', async () => {
    vi.mocked(getPlayer).mockResolvedValue({
      ...okPlayer,
      meta: { ...okPlayer.meta, cache: 'STALE' },
    } as never)

    const w = await mountAt()

    expect(w.text()).toContain('Vasilije')
    expect(w.text()).toContain('数据可能过期')
  })

  it('404 PLAYER_NOT_FOUND：渲染错误卡片且文案含「玩家不存在」', async () => {
    vi.mocked(getPlayer).mockRejectedValue(
      new ApiError('PLAYER_NOT_FOUND', 'player not found', 404),
    )

    const w = await mountAt()

    expect(w.text()).toContain('玩家不存在')
  })

  it('BAD_RESPONSE：渲染错误卡片（不白屏）', async () => {
    vi.mocked(getPlayer).mockRejectedValue(
      new ApiError('BAD_RESPONSE', '响应格式异常', 200),
    )

    const w = await mountAt()

    expect(w.text()).toContain('响应格式异常')
    expect(w.text().trim().length).toBeGreaterThan(0)
  })

  it('成功时用统一卡片外壳：一张卡里放标题、标签与缓存状态', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)

    const w = await mountAt()

    expect(w.findAll('.page-card')).toHaveLength(1)
    const card = w.find('.page-card')
    // 标题是玩家名，标签与缓存状态降级到说明行
    expect(card.find('.page-card__title').text()).toBe('Vasilije')
    expect(card.find('.page-card__lead').text()).toContain('#9QJ8L0')
    expect(card.find('.page-card__lead').text()).toContain('HIT')
    expect(card.find('.stat-grid').exists()).toBe(true)
    // 不再卡片套卡片
    expect(w.find('.detail-card').exists()).toBe(false)
  })

  it('没名字时标题退回标签', async () => {
    vi.mocked(getPlayer).mockResolvedValue({
      ...okPlayer,
      data: { ...okPlayer.data, name: '' },
    } as never)

    const w = await mountAt()

    expect(w.find('.page-card__title').text()).toBe('#9QJ8L0')
  })

  it('出错时标题仍是「玩家详情」，错误卡片在卡内', async () => {
    vi.mocked(getPlayer).mockRejectedValue(
      new ApiError('PLAYER_NOT_FOUND', 'player not found', 404),
    )

    const w = await mountAt()

    expect(w.find('.page-card__title').text()).toBe('玩家详情')
    expect(w.find('.page-card .error-card').exists()).toBe(true)
  })
})
