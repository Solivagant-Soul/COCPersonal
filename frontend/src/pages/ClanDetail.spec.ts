import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/request'

vi.mock('../api/endpoints', () => ({
  getClan: vi.fn(),
  getClanMembers: vi.fn(),
}))

import { getClan, getClanMembers } from '../api/endpoints'
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

/** 两条成员：一条整体晋升、一条下降；第二条没有联赛，用来验证「N 杯」兜底。 */
const okMembers = {
  data: [
    {
      tag: '#9QJ8L0',
      name: 'Vasilije',
      role: 'leader',
      townHallLevel: 16,
      trophies: 4902,
      clanRank: 2,
      previousClanRank: 3,
      donations: 2268,
      donationsReceived: 2182,
      league: {
        id: 29000022,
        name: 'Legend League',
        iconUrls: { small: 'https://x/l.png' },
      },
    },
    {
      tag: '#8L9P2R',
      name: 'Covert',
      role: 'coLeader',
      townHallLevel: 15,
      trophies: 4885,
      clanRank: 3,
      previousClanRank: 1,
      donations: 210,
      donationsReceived: 402,
      league: null,
    },
  ],
  meta: { cache: 'HIT', fetchedAt: '2026-01-01T00:00:00Z', ageSeconds: 5, ttlSeconds: 60 },
}

const emptyMembers = {
  data: [],
  meta: { cache: 'MISS', fetchedAt: '2026-01-01T00:00:00Z', ageSeconds: 0, ttlSeconds: 60 },
}

describe('ClanDetail', () => {
  beforeEach(() => {
    vi.mocked(getClan).mockReset()
    vi.mocked(getClanMembers).mockReset()
    vi.mocked(getClanMembers).mockResolvedValue(emptyMembers as never)
    localStorage.clear()
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

  it('详情页有「返回」按钮', async () => {
    vi.mocked(getClan).mockResolvedValue(okClan as never)

    const w = await mountAt()

    expect(w.find('.page-back').exists()).toBe(true)
  })

  it('关注按钮：点击后写入本地存储并变成「已关注」', async () => {
    vi.mocked(getClan).mockResolvedValue(okClan as never)

    const w = await mountAt()
    await w.find('.follow-btn').trigger('click')

    expect(w.find('.follow-btn').text()).toContain('已关注')
    expect(localStorage.getItem('cocpersonal.favorites')).toContain('#2PP')
  })

  it('头部显示部落徽章；没有 badgeUrls 时不留空框', async () => {
    vi.mocked(getClan).mockResolvedValue({
      ...okClan,
      data: { ...okClan.data, badgeUrls: { small: 'https://x/badge.png' } },
    } as never)

    const w = await mountAt()
    const badge = w.find('.clan-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.attributes('src')).toContain('badge.png')

    vi.mocked(getClan).mockResolvedValue(okClan as never)
    const without = await mountAt()
    expect(without.find('.clan-badge').exists()).toBe(false)
  })

  it('成员表：排名变化、玩家链接、职位、大本、段位与捐兵', async () => {
    vi.mocked(getClan).mockResolvedValue(okClan as never)
    vi.mocked(getClanMembers).mockResolvedValue(okMembers as never)

    const w = await mountAt()

    expect(w.find('.member-panel__title').text()).toContain('成员 · 2 人')
    const rows = w.findAll('.member-row')
    expect(rows).toHaveLength(2)

    const first = rows[0]
    expect(first.find('.member-rank-delta').text()).toBe('↑1')
    const link = first.find('.member-name')
    expect(link.text()).toBe('Vasilije')
    expect(link.attributes('href')).toContain('/players/%239QJ8L0')
    expect(first.text()).toContain('首领')
    expect(first.find('.member-cell__th').text()).toBe('TH16')
    expect(first.find('.member-cell__league').text()).toContain('传奇联赛')
    expect(first.find('.member-cell__donations').text()).toBe('2,268 / 2,182')

    // 排名下降用 ↓；没有联赛维表数据时退化成奖杯数
    expect(rows[1].find('.member-rank-delta').text()).toBe('↓2')
    expect(rows[1].find('.member-cell__league').text()).toContain('4,885 杯')
  })

  it('成员空列表：显示「暂无成员数据」且没有表行', async () => {
    vi.mocked(getClan).mockResolvedValue(okClan as never)
    vi.mocked(getClanMembers).mockResolvedValue(emptyMembers as never)

    const w = await mountAt()

    expect(w.find('.member-panel').text()).toContain('暂无成员数据')
    expect(w.findAll('.member-row')).toHaveLength(0)
  })

  it('成员接口失败：整块不显示，档案照常渲染', async () => {
    vi.mocked(getClan).mockResolvedValue(okClan as never)
    vi.mocked(getClanMembers).mockRejectedValue(
      new ApiError('UPSTREAM_FAULT', 'boom', 502),
    )

    const w = await mountAt()

    expect(w.text()).toContain('Reddit Zulu')
    expect(w.find('.member-panel').exists()).toBe(false)
    expect(w.find('.error-card').exists()).toBe(false)
  })
})
