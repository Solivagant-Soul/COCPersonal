import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearFavorites,
  FAVORITES_KEY,
  FAVORITES_LIMIT,
  isFavorite,
  readFavorites,
  removeFavorite,
  toggleFavorite,
} from './favorites'

describe('favorites', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('切换关注：第一次是加上，第二次是取消', () => {
    expect(isFavorite('#9QJ8L0', 'player')).toBe(false)

    expect(toggleFavorite({ tag: '#9QJ8L0', kind: 'player', name: 'Vasilije' })).toBe(true)
    expect(isFavorite('#9QJ8L0', 'player')).toBe(true)

    expect(toggleFavorite({ tag: '#9QJ8L0', kind: 'player' })).toBe(false)
    expect(isFavorite('#9QJ8L0', 'player')).toBe(false)
  })

  it('玩家与部落同标签互不影响', () => {
    toggleFavorite({ tag: '#2PP', kind: 'clan' })

    expect(isFavorite('#2PP', 'clan')).toBe(true)
    expect(isFavorite('#2PP', 'player')).toBe(false)
  })

  it('最新的排在最前，且写入时带上名字', () => {
    toggleFavorite({ tag: '#AAA', kind: 'player', name: '先关注的' })
    toggleFavorite({ tag: '#BBB', kind: 'clan', name: '后关注的' })

    const entries = readFavorites()
    expect(entries.map((e) => e.tag)).toEqual(['#BBB', '#AAA'])
    expect(entries[0].name).toBe('后关注的')
  })

  it('超过上限时丢掉最旧的', () => {
    for (let i = 0; i < FAVORITES_LIMIT + 3; i += 1) {
      toggleFavorite({ tag: `#T${i}`, kind: 'player' })
    }
    expect(readFavorites()).toHaveLength(FAVORITES_LIMIT)
  })

  it('存储被改坏时当作没有关注，而不是抛异常', () => {
    localStorage.setItem(FAVORITES_KEY, '{不是 JSON')
    expect(readFavorites()).toEqual([])
    expect(isFavorite('#9QJ8L0', 'player')).toBe(false)
  })

  it('数组里混进坏数据只丢那一条', () => {
    localStorage.setItem(
      FAVORITES_KEY,
      JSON.stringify([
        { tag: '#GOOD', kind: 'player', at: 2 },
        { tag: 123, kind: 'player', at: 1 },
      ]),
    )
    expect(readFavorites().map((e) => e.tag)).toEqual(['#GOOD'])
  })

  it('删除与清空', () => {
    toggleFavorite({ tag: '#AAA', kind: 'player' })
    removeFavorite('#AAA', 'player')
    expect(readFavorites()).toEqual([])

    toggleFavorite({ tag: '#BBB', kind: 'clan' })
    clearFavorites()
    expect(readFavorites()).toEqual([])
  })
})

describe('unitAssets', () => {
  it('英文名能查到中文素材名与目录', async () => {
    const { lookupUnitAsset } = await import('../data/unitAssets')

    expect(lookupUnitAsset('troops', 'Barbarian')).toEqual({ zh: '野蛮人', folder: 'army' })
    // 攻城机器在 API 里算 troops，但素材在 workshop 目录
    expect(lookupUnitAsset('troops', 'Wall Wrecker')).toEqual({
      zh: '攻城战车',
      folder: 'workshop',
    })
    expect(lookupUnitAsset('heroes', 'Archer Queen')).toEqual({
      zh: '弓箭女皇',
      folder: 'hero',
    })
  })

  it('没收录的名字返回 null（由组件退化成文字兜底）', async () => {
    const { lookupUnitAsset } = await import('../data/unitAssets')

    expect(lookupUnitAsset('troops', 'Brand New Troop')).toBeNull()
  })
})
