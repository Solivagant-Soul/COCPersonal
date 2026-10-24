import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({
  GLOBAL_LOCATION_ID: 32000000,
  getRankings: vi.fn(),
  getWarReportSeasons: vi.fn(),
  getWarReportSeasonRankings: vi.fn(),
}))

import {
  getRankings,
  getWarReportSeasonRankings,
  getWarReportSeasons,
} from '../api/endpoints'
import { installElementPlus } from '../plugins/element'
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

const seasonsPage = {
  data: {
    items: [
      { seasonId: '2026-10-05', players: 200, clans: 200, fetchedAt: null },
      { seasonId: '2026-09-07', players: 200, clans: 200, fetchedAt: null },
    ],
  },
  meta: rankingsPage.meta,
}

async function mountRankings() {
  await router.push({ name: 'rankings' })
  await router.isReady()
  // 用**生产同一个**安装函数：语言包只在 plugins/element.ts 配一处，
  // 测试自己传一份的话，「线上英文、测试中文」根本发现不了。
  const w = mount(Rankings, {
    global: { plugins: [router, { install: installElementPlus }] },
  })
  await flushPromises()
  return w
}

async function switchToSeason(w: Awaited<ReturnType<typeof mountRankings>>) {
  const tabs = w.findComponent({ name: 'ElTabs' })
  await tabs.vm.$emit('update:modelValue', 'season')
  await flushPromises()
}

describe('Rankings', () => {
  beforeEach(() => {
    vi.mocked(getRankings).mockReset()
    vi.mocked(getRankings).mockResolvedValue(rankingsPage as never)
    vi.mocked(getWarReportSeasons).mockReset()
    vi.mocked(getWarReportSeasonRankings).mockReset()
    vi.mocked(getWarReportSeasons).mockResolvedValue(seasonsPage as never)
    vi.mocked(getWarReportSeasonRankings).mockResolvedValue(rankingsPage as never)
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

  it('分页文案是中文，不是 Element Plus 默认的 Total / page', async () => {
    const w = await mountRankings()

    expect(w.text()).toContain('共 1 条')
    expect(w.text()).toContain('20条/页')
    expect(w.text()).not.toContain('Total')
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

  it('默认停在实时榜，不请求赛季数据', async () => {
    await mountRankings()
    expect(getRankings).toHaveBeenCalledWith('clans', 32000000, 1, 20)
    expect(getWarReportSeasons).not.toHaveBeenCalled()
  })

  it('切到赛季榜：默认选最新赛季并拉取', async () => {
    const w = await mountRankings()
    await switchToSeason(w)
    expect(getWarReportSeasons).toHaveBeenCalled()
    expect(getWarReportSeasonRankings).toHaveBeenCalledWith('2026-10-05', 'clans', 1, 20)
    expect(w.text()).toContain('数据来源：War Report')
  })

  it('切赛季回到第 1 页并重新拉取', async () => {
    const w = await mountRankings()
    await switchToSeason(w)
    vi.mocked(getWarReportSeasonRankings).mockClear()
    // 必须按 class 定位：el-pagination 的 layout 含 sizes，自己也会渲染一个
    // el-select，`findComponent({ name: 'ElSelect' })` 拿到的可能是分页器那个。
    const select = w.findComponent('.season-select')
    await select.vm.$emit('update:modelValue', '2026-09-07')
    await flushPromises()
    expect(getWarReportSeasonRankings).toHaveBeenCalledWith('2026-09-07', 'clans', 1, 20)
  })

  it('赛季列表为空时显示空态，不卡在 loading', async () => {
    vi.mocked(getWarReportSeasons).mockResolvedValue({
      data: { items: [] },
      meta: rankingsPage.meta,
    } as never)
    const w = await mountRankings()
    await switchToSeason(w)
    expect(w.text()).toContain('暂无赛季数据')
    // LoadingBlock 用的是 skeleton、没有「加载中」字样，所以断言 DOM 而不是文案
    expect(w.find('.loading-block').exists()).toBe(false)
    // 没有赛季可选时**绝不能**去拉榜：那会打出一个 /seasons//clans（快照为空）
    // 的请求，后端 400，页面从"暂无数据"变成"查询失败"
    expect(getWarReportSeasonRankings).not.toHaveBeenCalled()
  })

  it('切回实时榜再切回来，不重复请求赛季列表', async () => {
    const w = await mountRankings()
    await switchToSeason(w)
    const tabs = w.findComponent({ name: 'ElTabs' })
    await tabs.vm.$emit('update:modelValue', 'realtime')
    await flushPromises()
    await switchToSeason(w)
    expect(getWarReportSeasons).toHaveBeenCalledTimes(1)
  })

  it('赛季榜切部落/玩家只重拉赛季榜，不碰实时榜', async () => {
    const w = await mountRankings()
    await switchToSeason(w)
    vi.mocked(getRankings).mockClear()
    vi.mocked(getWarReportSeasonRankings).mockClear()

    // 第一个 radio group 在实时面板（非 lazy，切走后仍留在 DOM 里），第二个才是赛季的
    const groups = w.findAllComponents({ name: 'ElRadioGroup' })
    await groups[1].setValue('players')
    await flushPromises()

    expect(getWarReportSeasonRankings).toHaveBeenCalledWith('2026-10-05', 'players', 1, 20)
    expect(getRankings).not.toHaveBeenCalled()
  })
})
