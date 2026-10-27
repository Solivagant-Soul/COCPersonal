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

/** 可控 resolve 的响应：用来制造「先发的请求后回来」。 */
function deferredPage() {
  let resolve!: (value: unknown) => void
  const promise = new Promise<unknown>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

/** 取**当前**的赛季分页器。
 *
 * 不能把包装器存到变量里反复用：拉取期间 `LoadingBlock` 会把「表格 + 分页器」
 * 整个卸载重建，之前拿到的包装器已经脱离组件树，对它 `$emit` 什么也不会发生
 * （表现为「事件发出去了但父组件毫无反应」）。每次操作前重新取。
 *
 * 按 `total` 定位而不是按下标：实时榜与赛季榜各有一个分页器，只有赛季这个的
 * `total` 是 200（实时榜是 1）。
 */
function seasonPager(w: Awaited<ReturnType<typeof mountRankings>>) {
  const pager = w
    .findAllComponents({ name: 'ElPagination' })
    .find((p) => p.props('total') === 200)
  if (!pager) throw new Error('没找到赛季分页器（total=200）')
  return pager
}

/** 造一页榜单数据（name 决定渲染出的名字，用于断言是哪一次响应）。 */
function pageNamed(name: string, total = 1) {
  return {
    data: { items: [{ ...clanRow, name }], total, kind: 'clans' },
    meta: rankingsPage.meta,
  }
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

  it('用与其他页签一致的卡片外壳：标题、说明与榜单内容都在同一张卡里', async () => {
    const w = await mountRankings()

    expect(w.findAll('.page-card')).toHaveLength(1)
    const card = w.find('.page-card')
    expect(card.find('.page-card__title').text()).toBe('排行榜')
    expect(card.find('.page-card__lead').exists()).toBe(true)
    // 榜单切换器、工具行与表格都在卡内
    expect(card.find('.el-tabs').exists()).toBe(true)
    expect(card.find('.toolbar').exists()).toBe(true)
    expect(card.text()).toContain('Reddit Zulu')
  })

  it('实时榜显示 meta.fetchedAt（北京时间），这是「榜单多久以前抓的」', async () => {
    const w = await mountRankings()

    // 夹具 fetchedAt 是 2026-01-01T00:00:00Z → 北京时间 08:00
    expect(w.text()).toContain('数据更新于 2026-01-01 08:00')
  })

  it('后端没给 fetchedAt 时不显示半截文案', async () => {
    vi.mocked(getRankings).mockResolvedValue({
      ...rankingsPage,
      meta: { ...rankingsPage.meta, fetchedAt: null },
    } as never)

    const w = await mountRankings()

    expect(w.text()).not.toContain('数据更新于')
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

  it('翻到第 2 页后切赛季，回到第 1 页重拉', async () => {
    // total 必须大于一页，否则分页器根本翻不到第 2 页
    vi.mocked(getWarReportSeasonRankings).mockResolvedValue({
      ...pageNamed('占位', 200),
    } as never)

    const w = await mountRankings()
    await switchToSeason(w)

    // 先把赛季榜真的翻到第 2 页 —— 不先翻走的话，「切赛季后是第 1 页」
    // 在 page 从来没离开过 1 的情况下永远成立，测不出东西。
    await seasonPager(w).vm.$emit('update:current-page', 2)
    await seasonPager(w).vm.$emit('current-change', 2)
    await flushPromises()
    expect(getWarReportSeasonRankings).toHaveBeenLastCalledWith(
      '2026-10-05',
      'clans',
      2,
      20,
    )

    vi.mocked(getWarReportSeasonRankings).mockClear()
    // 必须按 class 定位：el-pagination 的 layout 含 sizes，自己也会渲染一个
    // el-select，`findComponent({ name: 'ElSelect' })` 拿到的可能是分页器那个。
    const select = w.findComponent('.season-select')
    await select.vm.$emit('update:modelValue', '2026-09-07')
    await flushPromises()
    expect(getWarReportSeasonRankings).toHaveBeenCalledWith('2026-09-07', 'clans', 1, 20)
  })

  it('翻到第 2 页后改每页条数，也回到第 1 页', async () => {
    vi.mocked(getWarReportSeasonRankings).mockResolvedValue({
      ...pageNamed('占位', 200),
    } as never)

    const w = await mountRankings()
    await switchToSeason(w)
    await seasonPager(w).vm.$emit('update:current-page', 2)
    await seasonPager(w).vm.$emit('current-change', 2)
    await flushPromises()
    expect(getWarReportSeasonRankings).toHaveBeenLastCalledWith(
      '2026-10-05',
      'clans',
      2,
      20,
    )

    vi.mocked(getWarReportSeasonRankings).mockClear()
    // 上面的拉取已经把分页器卸载重建过一次，这里必须重新取
    await seasonPager(w).vm.$emit('update:page-size', 100)
    await seasonPager(w).vm.$emit('size-change', 100)
    await flushPromises()

    expect(getWarReportSeasonRankings).toHaveBeenCalledWith('2026-10-05', 'clans', 1, 100)
  })

  it('晚到的旧响应不覆盖新响应（实时榜切类型）', async () => {
    const first = deferredPage()
    const second = deferredPage()
    const queue = [first, second]
    vi.mocked(getRankings).mockImplementation(
      () => queue.shift()!.promise as never,
    )

    const w = await mountRankings() // 第 1 次请求（部落）挂起
    const group = w.findComponent({ name: 'ElRadioGroup' })
    await group.setValue('players') // 第 2 次请求（玩家）挂起
    await flushPromises()

    // 后发的先回来：列表显示新响应
    second.resolve(pageNamed('新响应'))
    await flushPromises()
    expect(w.text()).toContain('新响应')
    expect(w.find('.loading-block').exists()).toBe(false)

    // 先发的后回来：必须被丢弃，否则列表会退回旧类型的数据，
    // 而单选按钮与分页器还停在新状态上 —— 用户不手动再切一次就不会自愈。
    first.resolve(pageNamed('旧响应'))
    await flushPromises()
    expect(w.text()).toContain('新响应')
    expect(w.text()).not.toContain('旧响应')
  })

  it('晚到的旧响应不覆盖新响应（切赛季）', async () => {
    const first = deferredPage()
    const second = deferredPage()
    const queue = [first, second]
    vi.mocked(getWarReportSeasonRankings).mockImplementation(
      () => queue.shift()!.promise as never,
    )

    const w = await mountRankings()
    await switchToSeason(w) // 默认赛季，请求挂起
    const select = w.findComponent('.season-select')
    await select.vm.$emit('update:modelValue', '2026-09-07') // 新赛季，请求挂起
    await flushPromises()

    second.resolve(pageNamed('九月榜'))
    await flushPromises()
    expect(w.text()).toContain('九月榜')

    first.resolve(pageNamed('十月榜'))
    await flushPromises()
    expect(w.text()).toContain('九月榜')
    expect(w.text()).not.toContain('十月榜')
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
