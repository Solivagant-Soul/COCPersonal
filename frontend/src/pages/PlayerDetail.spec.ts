import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/request'

vi.mock('../api/endpoints', () => ({
  getPlayer: vi.fn(),
  getPlayerBattles: vi.fn(),
}))

import { getPlayer, getPlayerBattles } from '../api/endpoints'
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
  data: {
    tag: '#9QJ8L0',
    name: 'Vasilije',
    expLevel: 205,
    trophies: 4902,
    clan: { tag: '#2PP', name: 'Reddit Zulu' },
    // 传奇段位：战报区只对传奇玩家显示（见 PlayerDetail 的 isLegendLeague）
    league: { id: 105000036, name: 'Legend I' },
  },
  meta: { cache: 'HIT', fetchedAt: '2026-01-01T00:00:00Z', ageSeconds: 5, ttlSeconds: 60 },
}

/** 两条进攻 + 一条防守：汇总只该统计进攻。 */
const okBattles = {
  data: {
    items: [
      {
        timestamp: '2026-10-27T10:14:00.000Z',
        kind: 'attack',
        stars: 3,
        destructionPercentage: 100,
        opponent: { tag: '#AAA111', name: 'Rival One' },
        army: {
          troops: [{ name: 'Dragon Rider', level: 3, village: 'home' }],
          spells: [{ name: 'Rage Spell', level: 6, village: 'home' }],
          heroes: [{ name: 'Grand Warden', level: 70, village: 'home' }],
        },
      },
      {
        timestamp: '2026-10-27T09:37:00.000Z',
        kind: 'attack',
        stars: 2,
        destructionPercentage: 84,
        opponent: { tag: '#AAA222', name: 'Rival Two' },
        army: { troops: [{ name: 'Root Rider', level: 4, village: 'home' }] },
      },
      {
        timestamp: '2026-10-27T08:54:00.000Z',
        kind: 'defense',
        stars: 1,
        destructionPercentage: 63,
        opponent: { tag: '#BBB222', name: 'Rival Three' },
        army: null,
      },
    ],
  },
  meta: { cache: 'HIT', fetchedAt: '2026-01-01T00:00:00Z', ageSeconds: 5, ttlSeconds: 60 },
}

const emptyBattles = {
  data: { items: [] },
  meta: { cache: 'MISS', fetchedAt: '2026-01-01T00:00:00Z', ageSeconds: 0, ttlSeconds: 60 },
}

describe('PlayerDetail', () => {
  beforeEach(() => {
    vi.mocked(getPlayer).mockReset()
    vi.mocked(getPlayerBattles).mockReset()
    vi.mocked(getPlayerBattles).mockResolvedValue(emptyBattles as never)
    localStorage.clear()
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

  it('说明行分两行：`#标签 · 部落名` 与 `缓存状态`', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)

    const w = await mountAt()

    const main = w.find('.page-card__lead-main')
    expect(main.text()).toContain('#9QJ8L0')
    expect(main.text()).toContain('Reddit Zulu')
    expect(main.find('a.clan-link').exists()).toBe(true)

    const sub = w.find('.page-card__lead-sub')
    expect(sub.text()).toContain('HIT')
    // 缓存状态不再和标签挤在同一行
    expect(main.text()).not.toContain('HIT')
  })

  it('联赛格：中文名 + 官方图标', async () => {
    vi.mocked(getPlayer).mockResolvedValue({
      ...okPlayer,
      data: {
        ...okPlayer.data,
        league: {
          id: 105000036,
          name: 'Legend I',
          iconUrls: { small: 'https://api-assets.clashofclans.com/leagues/small/l.png' },
        },
      },
    } as never)

    const w = await mountAt()

    expect(w.find('.stat-grid').text()).toContain('传奇 I')
    const icon = w.find('.stat-grid__icon')
    expect(icon.exists()).toBe(true)
    expect(icon.attributes('src')).toContain('l.png')
  })

  it('练度区：兵种/攻城机器/法术/英雄/战宠分组渲染，夜世界单位不出现', async () => {
    vi.mocked(getPlayer).mockResolvedValue({
      ...okPlayer,
      data: {
        ...okPlayer.data,
        troops: [
          { name: 'Barbarian', level: 11, maxLevel: 12, village: 'home' },
          { name: 'Super Barbarian', level: 11, maxLevel: 11, village: 'home' },
          { name: 'Wall Wrecker', level: 5, maxLevel: 5, village: 'home' },
          { name: 'L.A.S.S.I', level: 10, maxLevel: 10, village: 'home' },
          { name: 'Raged Barbarian', level: 18, maxLevel: 18, village: 'builderBase' },
        ],
        spells: [{ name: 'Lightning Spell', level: 10, maxLevel: 11, village: 'home' }],
        heroes: [{ name: 'Barbarian King', level: 95, maxLevel: 95, village: 'home' }],
      },
    } as never)

    const w = await mountAt()

    const labels = w.findAll('.unit-group__label').map((n) => n.text())
    expect(labels).toEqual(['兵种', '攻城机器', '法术', '英雄', '战宠'])

    // 主村 1 兵 + 1 攻城机器 + 1 法术 + 1 英雄 + 1 战宠；超级兵与夜世界那条都被过滤掉
    expect(w.findAll('.unit-tile')).toHaveLength(5)
    expect(w.text()).not.toContain('超级野蛮人')
    expect(w.text()).not.toContain('Raged Barbarian')
    // 等级角标照常显示
    expect(w.find('.unit-tile__level').text()).toBe('11')
  })

  it('满级单位的等级数字换成金底（与普通等级区分）', async () => {
    vi.mocked(getPlayer).mockResolvedValue({
      ...okPlayer,
      data: {
        ...okPlayer.data,
        troops: [
          { name: 'Barbarian', level: 8, maxLevel: 12, village: 'home' },
          { name: 'Archer', level: 12, maxLevel: 12, village: 'home' },
        ],
      },
    } as never)

    const w = await mountAt()

    const maxTile = w.find('.unit-tile--max')
    expect(maxTile.exists()).toBe(true)
    // 只有练满的那个带 --max 标记，8/12 的那个不带
    expect(w.findAll('.unit-tile--max')).toHaveLength(1)
    expect(maxTile.find('.unit-tile__level').text()).toBe('12')
  })

  it('大本营图标：按 townHallLevel 取对应素材', async () => {
    vi.mocked(getPlayer).mockResolvedValue({
      ...okPlayer,
      data: { ...okPlayer.data, townHallLevel: 15 },
    } as never)

    const w = await mountAt()

    const icon = w.find('.page-card__th')
    expect(icon.exists()).toBe(true)
    expect(icon.attributes('src')).toBe('/pictures/townhall/TH15.png')
    expect(icon.attributes('alt')).toContain('15')
  })

  it('大本营等级缺失时不渲染图标', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)

    const w = await mountAt()

    expect(w.find('.page-card__th').exists()).toBe(false)
  })

  it('关注按钮：点击后写入本地存储并变成「已关注」', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)

    const w = await mountAt()
    const btn = w.find('.follow-btn')
    expect(btn.text()).toContain('关注')

    await btn.trigger('click')

    expect(w.find('.follow-btn').text()).toContain('已关注')
    expect(localStorage.getItem('cocpersonal.favorites')).toContain('#9QJ8L0')
  })

  it('关注按钮：已关注只点亮五角星，按钮本身不变色', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)

    const w = await mountAt()
    await w.find('.follow-btn').trigger('click')

    const btn = w.find('.follow-btn')
    expect(btn.find('.follow-btn__star').text()).toBe('★')
    // 曾经的实现给按钮加了 type="warning"，整颗按钮变金
    expect(btn.classes()).not.toContain('el-button--warning')
  })

  it('返回按钮在卡片外（页面左上角），不在卡片里', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)

    const w = await mountAt()

    const back = w.find('.page-back')
    expect(back.exists()).toBe(true)
    expect(w.find('.page-card .page-back').exists()).toBe(false)
  })

  it('非传奇段位：不显示传奇联赛战报，也不去请求战报', async () => {
    vi.mocked(getPlayer).mockResolvedValue({
      ...okPlayer,
      data: {
        ...okPlayer.data,
        league: { id: 105000033, name: 'Electro League 33' },
      },
    } as never)

    const w = await mountAt()

    expect(w.find('.battle-panel').exists()).toBe(false)
    expect(getPlayerBattles).not.toHaveBeenCalled()
  })

  it('联赛格：新天梯的 `Electro League 33` 翻成中文', async () => {
    vi.mocked(getPlayer).mockResolvedValue({
      ...okPlayer,
      data: {
        ...okPlayer.data,
        league: {
          id: 105000033,
          name: 'Electro League 33',
          iconUrls: { small: 'https://api-assets.clashofclans.com/leagues/small/e.png' },
        },
      },
    } as never)

    const w = await mountAt()

    expect(w.find('.stat-grid').text()).toContain('雷电 33')
  })

  it('战报区：逐条渲染时间、星级、摧毁率、攻/防标签与小图标', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)
    vi.mocked(getPlayerBattles).mockResolvedValue(okBattles as never)

    const w = await mountAt()

    expect(w.find('.battle-panel').exists()).toBe(true)
    expect(w.find('.battle-panel__title').text()).toContain('传奇联赛战报')

    const rows = w.findAll('.battle-row')
    expect(rows).toHaveLength(3)

    // 北京时间（UTC+8），只到分钟
    expect(rows[0].find('.battle-row__time').text()).toBe('10-27 18:14')
    expect(rows[0].find('.battle-row__stars').text()).toBe('★★★')
    expect(rows[0].find('.battle-row__destruction').text()).toBe('100%')
    expect(rows[0].find('.battle-row__kind').text()).toBe('进攻')
    expect(rows[1].find('.battle-row__stars').text()).toBe('★★')
    expect(rows[2].find('.battle-row__kind').text()).toBe('防守')

    // 进攻条目附队伍，防守条目没有队伍
    expect(rows[0].findAll('.unit-tile--small')).toHaveLength(3)
    expect(rows[2].findAll('.unit-tile').length).toBe(0)
  })

  it('战报汇总：只统计进攻（场次 / 三星率 / 场均摧毁）', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)
    vi.mocked(getPlayerBattles).mockResolvedValue(okBattles as never)

    const w = await mountAt()

    const summary = w.find('.battle-summary').text()
    // 2 场进攻（3★ + 2★），防守那条不该算进来
    expect(summary).toContain('进攻 2 场')
    expect(summary).toContain('三星率 50%')
    expect(summary).toContain('场均摧毁 92%')
  })

  it('战报空态：没有战报时给一句说明，不渲染列表', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)
    vi.mocked(getPlayerBattles).mockResolvedValue(emptyBattles as never)

    const w = await mountAt()

    expect(w.find('.battle-panel').text()).toContain('该玩家最近没有传奇联赛战报')
    expect(w.findAll('.battle-row')).toHaveLength(0)
    expect(w.find('.battle-summary').exists()).toBe(false)
  })

  it('战报请求失败：整块不显示，档案照常渲染且不报错', async () => {
    vi.mocked(getPlayer).mockResolvedValue(okPlayer as never)
    vi.mocked(getPlayerBattles).mockRejectedValue(
      new ApiError('UPSTREAM_FAULT', 'boom', 502),
    )

    const w = await mountAt()

    expect(w.text()).toContain('Vasilije')
    expect(w.find('.battle-panel').exists()).toBe(false)
    expect(w.find('.error-card').exists()).toBe(false)
  })
})
