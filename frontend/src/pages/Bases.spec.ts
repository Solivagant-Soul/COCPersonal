import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({ getBases: vi.fn(), uploadBase: vi.fn() }))

import { getBases } from '../api/endpoints'
import { ApiError } from '../api/request'
import { installElementPlus } from '../plugins/element'
import Bases from './Bases.vue'

const items = [
  {
    id: 1,
    title: '#1 18本传奇防守阵',
    thLevel: 18,
    layoutLink: 'https://link.clashofclans.com/?id=a',
    imagePath: '/media/bases/a.jpg',
    sourceUrl: 'https://b23.tv/x',
    sourceSite: 'bilibili',
    createdAt: '2026-11-04T00:00:00Z',
  },
  {
    id: 2,
    title: '#2 国服手摆',
    thLevel: 18,
    layoutLink: null,
    imagePath: null,
    sourceUrl: null,
    sourceSite: 'bilibili',
    createdAt: '2026-11-04T00:00:00Z',
  },
]

function mountBases() {
  return mount(Bases, { global: { plugins: [{ install: installElementPlus }] } })
}

beforeEach(() => {
  vi.mocked(getBases).mockReset()
  vi.mocked(getBases).mockResolvedValue({
    data: { items, total: 3 },
    meta: { cache: 'HIT', fetchedAt: null, ageSeconds: null, ttlSeconds: 0 },
  } as never)
})

it('渲染阵型卡片与 TH 徽标', async () => {
  const w = mountBases()
  await flushPromises()
  expect(w.findAll('.base-card')).toHaveLength(2)
  expect(w.text()).toContain('#1 18本传奇防守阵')
  expect(w.text()).toContain('TH18')
})

it('无链接的条目不渲染复制按钮', async () => {
  const w = mountBases()
  await flushPromises()
  expect(w.findAll('.base-card__copy')).toHaveLength(1)
  expect(w.text()).toContain('国服需照图手摆')
})

it('复制按钮写入剪贴板', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  const w = mountBases()
  await flushPromises()
  await w.find('.base-card__copy').trigger('click')
  expect(writeText).toHaveBeenCalledWith('https://link.clashofclans.com/?id=a')
})

it('加载更多请求下一页', async () => {
  const w = mountBases()
  await flushPromises()
  await w.find('.bases-more').trigger('click')
  await flushPromises()
  expect(getBases).toHaveBeenLastCalledWith(null, 2, 24)
})

it('切换等级重置到第一页并带 th_level', async () => {
  const w = mountBases()
  await flushPromises()
  w.findComponent({ name: 'ElRadioGroup' }).vm.$emit('update:modelValue', 18)
  await flushPromises()
  expect(getBases).toHaveBeenLastCalledWith(18, 1, 24)
})

it('等级筛选包含 16 / 17 / 18 本', async () => {
  const w = mountBases()
  await flushPromises()
  const labels = w.findAll('.bases-filter .el-radio-button').map((node) => node.text())
  expect(labels).toEqual(['全部', '16 本', '17 本', '18 本'])
})

it('加载更多失败时保留已有卡片，不整页报错', async () => {
  const w = mountBases()
  await flushPromises()
  vi.mocked(getBases).mockRejectedValueOnce(new ApiError('NETWORK_ERROR', '网络异常', 0))

  await w.find('.bases-more').trigger('click')
  await flushPromises()

  expect(w.findAll('.base-card')).toHaveLength(2)
  expect(w.find('.error-card').exists()).toBe(false)

  // 页码已回退：再点一次仍然请求第 2 页，而不是跳页。
  await w.find('.bases-more').trigger('click')
  await flushPromises()
  expect(getBases).toHaveBeenLastCalledWith(null, 2, 24)
})

it('点击上传按钮打开弹窗', async () => {
  const w = mountBases()
  await flushPromises()
  await w.find('.bases-upload').trigger('click')
  expect(w.findComponent({ name: 'ElDialog' }).props('modelValue')).toBe(true)
})
