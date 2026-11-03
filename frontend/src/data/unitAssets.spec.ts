import { describe, expect, it } from 'vitest'

import { classifyTroop, lookupUnitAsset } from './unitAssets'

describe('classifyTroop', () => {
  it('普通兵种归 troops', () => {
    expect(classifyTroop('Barbarian')).toEqual({
      asset: { zh: '野蛮人', folder: 'army' },
      group: 'troops',
    })
  })

  it('攻城机器按素材目录归 siege（API 里它们也在 troops 里）', () => {
    const { asset, group } = classifyTroop('Wall Wrecker')
    expect(group).toBe('siege')
    expect(asset?.folder).toBe('workshop')
  })

  it('战宠归 pets（上游没有独立的 pets 字段）', () => {
    const { asset, group } = classifyTroop('L.A.S.S.I')
    expect(group).toBe('pets')
    expect(asset?.zh).toBe('莱希')
  })

  it('查不到的名字按普通兵种处理，素材为 null（由组件退化成文字）', () => {
    expect(classifyTroop('Brand New Troop')).toEqual({ asset: null, group: 'troops' })
  })
})

describe('超级兵标记', () => {
  it('超级兵带 superTroop 标记', () => {
    expect(lookupUnitAsset('troops', 'Super Barbarian')?.superTroop).toBe(true)
    expect(lookupUnitAsset('troops', 'Super Yeti')?.superTroop).toBe(true)
    expect(lookupUnitAsset('troops', 'Sneaky Goblin')?.superTroop).toBe(true)
  })

  it('本体兵种不带标记，免得被一起过滤掉', () => {
    expect(lookupUnitAsset('troops', 'Barbarian')?.superTroop).toBeUndefined()
    expect(lookupUnitAsset('troops', 'Meteor Golem')?.superTroop).toBeUndefined()
  })
})
