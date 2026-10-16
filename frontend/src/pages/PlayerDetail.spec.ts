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
})
