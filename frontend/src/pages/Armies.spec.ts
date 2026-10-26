import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({ getArmies: vi.fn() }))

import { getArmies } from '../api/endpoints'
import { ApiError } from '../api/request'
import { installElementPlus } from '../plugins/element'
import Armies from './Armies.vue'

const SHARE_CODE =
  'h0p9e14_32-1p3e17_20-2p16e24_5-7p4e52_53' +
  'i1x5-2x58-1x64' +
  'd1x53-1x98' +
  'u9x132-5x7-1x150-2x109-2x28-2x5-1x135-1x58-1x3-2x4-2x26-2x1-1x82' +
  's3x10-1x35-1x9-3x120-1x70-1x5'

const army = {
  position: 1,
  name: 'Thrower',
  canonicalKey: 'k1',
  armyShareCode: SHARE_CODE,
  armyLink: `https://link.clashofclans.com/?action=CopyArmy&army=${SHARE_CODE}`,
  playerCount: 54,
  useCount: 332,
  percentage: 27.27,
  averageStars: 2.73,
  averageDestruction: 97.25,
}

const page = {
  data: { items: [army] },
  meta: { cache: 'HIT', fetchedAt: null, ageSeconds: null, ttlSeconds: 86400 },
}

/** 测试里替换过的 clipboard 要还原，别把全局状态漏给同文件后面的用例。 */
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')

function mountArmies() {
  return mount(Armies, { global: { plugins: [{ install: installElementPlus }] } })
}

describe('Armies', () => {
  beforeEach(() => {
    vi.mocked(getArmies).mockReset()
    vi.mocked(getArmies).mockResolvedValue(page as never)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    if (originalClipboard) {
      Object.defineProperty(navigator, 'clipboard', originalClipboard)
    } else {
      // jsdom 默认没有 clipboard，删掉属性即可回到原状
      delete (navigator as { clipboard?: unknown }).clipboard
    }
  })

  it('渲染中文配兵名、使用率与平均星', async () => {
    const w = mountArmies()
    await flushPromises()
    expect(w.text()).toContain('巨矛投手')
    expect(w.text()).not.toContain('Thrower')
    expect(w.text()).toContain('27.3%')
    expect(w.text()).toContain('2.73')
    // 其余关键指标也钉住：只测名字与百分比时，把 使用次数/玩家数/摧毁率 接到
    // 错误字段上一样能过
    expect(w.text()).toContain('332')
    expect(w.text()).toContain('54')
    expect(w.text()).toContain('97.25')
    expect(w.text()).toContain('数据来源：War Report')
  })

  it('把配兵分享码渲染成图标，详情里给出数量', async () => {
    const w = mountArmies()
    await flushPromises()

    // 预览里能看到部队 / 法术 / 英雄 / 城堡四组
    expect(w.text()).toContain('部队')
    expect(w.text()).toContain('法术')
    expect(w.text()).toContain('英雄')
    expect(w.text()).toContain('城堡')
    // 9 个巨矛投手的数量角标
    expect(w.findAll('.army-unit')).not.toHaveLength(0)
    expect(w.text()).toContain('9')

    // 默认不展开；点「详情」后才给出逐项数量
    expect(w.find('.army-composition__detail').exists()).toBe(false)
    await w.find('.army-composition__toggle').trigger('click')
    expect(w.find('.army-composition__detail').exists()).toBe(true)
    expect(w.find('.army-composition__detail').text()).toContain('巨矛投手')
    expect(w.find('.army-composition__detail').text()).toContain('×9')
    expect(w.find('.army-composition__detail').text()).toContain('×5')
    // 详情里装备是文本行，不加载几 MB 的装备图
    expect(w.find('.army-composition__detail').text()).toContain('尖刺足球')
  })

  it('每张卡的复制按钮有自己的无障碍名（不是一排同名按钮）', async () => {
    const second = { ...army, position: 2, name: 'Super Bowler', canonicalKey: 'k2' }
    vi.mocked(getArmies).mockResolvedValue({
      ...page,
      data: { items: [army, second] },
    } as never)

    const w = mountArmies()
    await flushPromises()

    const buttons = w.findAll('.army-card__copy')
    expect(buttons).toHaveLength(2)
    // 屏幕阅读器里一排"复制阵容链接"分不出是哪张卡
    expect(buttons[0].attributes('aria-label')).toContain('巨矛投手')
    expect(buttons[1].attributes('aria-label')).toContain('超级巨石投手')
    expect(buttons[0].attributes('aria-label')).not.toBe(
      buttons[1].attributes('aria-label'),
    )
  })

  it('空数据显示空态', async () => {
    vi.mocked(getArmies).mockResolvedValue({
      data: { items: [] },
      meta: page.meta,
    } as never)
    const w = mountArmies()
    await flushPromises()
    expect(w.text()).toContain('暂无数据')
  })

  it('请求失败显示错误卡片，不卡在 loading', async () => {
    vi.mocked(getArmies).mockRejectedValue(
      new ApiError('UPSTREAM_UNAVAILABLE', 'upstream down', 502),
    )
    const w = mountArmies()
    await flushPromises()

    expect(w.find('.loading-block').exists()).toBe(false)
    expect(w.text()).toContain('上游服务暂时不可用，请稍后重试')
    // 失败时页尾署名也要在
    expect(w.text()).toContain('数据来源：War Report')
  })

  it('错误卡片的重试会重新拉取', async () => {
    vi.mocked(getArmies).mockRejectedValueOnce(
      new ApiError('UPSTREAM_UNAVAILABLE', 'upstream down', 502),
    )
    const w = mountArmies()
    await flushPromises()

    await w.find('.error-card__retry').trigger('click')
    await flushPromises()

    expect(getArmies).toHaveBeenCalledTimes(2)
    expect(w.text()).toContain('巨矛投手')
  })

  it('有 clipboard 时复制链接而不打开新窗口', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const w = mountArmies()
    await flushPromises()

    await w.find('.army-card__copy').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith(army.armyLink)
    expect(open).not.toHaveBeenCalled()
    // 成功提示是 ElMessage（没有全局 $message，组件里显式 import）
    expect(document.body.textContent).toContain('已复制阵容链接')
  })

  it('没有 clipboard 时退化打开链接，不抛未捕获异常', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const w = mountArmies()
    await flushPromises()
    await w.find('.army-card__copy').trigger('click')
    await flushPromises()
    expect(open).toHaveBeenCalledWith(army.armyLink, '_blank', 'noopener')
  })

  it('写剪贴板被拒时同样退化成打开链接', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    })
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const w = mountArmies()
    await flushPromises()
    await w.find('.army-card__copy').trigger('click')
    await flushPromises()
    expect(open).toHaveBeenCalledWith(army.armyLink, '_blank', 'noopener')
  })
})
