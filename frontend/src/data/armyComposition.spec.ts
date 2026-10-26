import { describe, expect, it } from 'vitest'

import { armyTitleZh, parseArmyShareCode } from './armyComposition'

/** 真实 War Report 分享码（Thrower，2026-10-26）。 */
const CODE =
  'h0p9e14_32-1p3e17_20-2p16e24_5-7p4e52_53' +
  'i1x5-2x58-1x64' +
  'd1x53-1x98' +
  'u9x132-5x7-1x150-2x109-2x28-2x5-1x135-1x58-1x3-2x4-2x26-2x1-1x82' +
  's3x10-1x35-1x9-3x120-1x70-1x5'

function group(key: string) {
  return parseArmyShareCode(CODE).find((item) => item.key === key)
}

describe('parseArmyShareCode', () => {
  it('解析部队、法术、英雄、城堡四组', () => {
    expect(parseArmyShareCode(CODE).map((item) => item.label)).toEqual([
      '部队',
      '法术',
      '英雄',
      '城堡',
    ])
  })

  it('u 段按“数量x id”还原，并区分部队与攻城机器', () => {
    const troops = group('troops')
    expect(troops).toBeTruthy()
    expect(troops?.units).toContainEqual({
      kind: 'troop',
      id: 132,
      name: '巨矛投手',
      count: 9,
    })
    expect(troops?.units).toContainEqual({
      kind: 'troop',
      id: 7,
      name: '天使',
      count: 5,
    })
    // 135 = 部队发射器，属于攻城机器（workshop 目录）
    expect(troops?.units).toContainEqual({
      kind: 'siege',
      id: 135,
      name: '部队发射器',
      count: 1,
    })
  })

  it('s 段是法术', () => {
    const spells = group('spells')
    expect(spells?.units).toContainEqual({
      kind: 'spell',
      id: 10,
      name: '地震法术',
      count: 3,
    })
    expect(spells?.units).toContainEqual({
      kind: 'spell',
      id: 120,
      name: '图腾法术',
      count: 3,
    })
  })

  it('h 段拆出英雄、战宠与两件装备', () => {
    const heroes = group('heroes')
    expect(heroes?.units).toContainEqual({
      kind: 'hero',
      id: 0,
      name: '野蛮人之王',
      count: 1,
    })
    expect(heroes?.units).toContainEqual({
      kind: 'pet',
      id: 9,
      name: '冰牙',
      count: 1,
    })
    expect(heroes?.units).toContainEqual({
      kind: 'equipment',
      id: 14,
      name: '尖刺足球',
      count: 1,
    })
    expect(heroes?.units).toContainEqual({
      kind: 'equipment',
      id: 32,
      name: '灵蛇手镯',
      count: 1,
    })
    // 第二个英雄带 m 段（皮肤/形态），不能被当成非法条目丢掉
    expect(heroes?.units).toContainEqual({
      kind: 'hero',
      id: 1,
      name: '弓箭女皇',
      count: 1,
    })
  })

  it('i / d 段合并成城堡援军', () => {
    const castle = group('castle')
    expect(castle?.units).toContainEqual({
      kind: 'troop',
      id: 58,
      name: '戈仑冰人',
      count: 2,
    })
    expect(castle?.units).toContainEqual({
      kind: 'spell',
      id: 53,
      name: '回溯法术',
      count: 1,
    })
  })

  it('空串、乱码与缺段都不抛异常', () => {
    expect(parseArmyShareCode('')).toEqual([])
    expect(parseArmyShareCode('not-a-code')).toEqual([])
    expect(parseArmyShareCode('u9x9999')).toEqual([
      {
        key: 'troops',
        label: '部队',
        units: [{ kind: 'troop', id: 9999, name: '未知单位 #9999', count: 9 }],
      },
    ])
  })
})

describe('armyTitleZh', () => {
  it('直译已知阵容', () => {
    expect(armyTitleZh('Thrower')).toBe('巨矛投手')
    expect(armyTitleZh('Super Bowler')).toBe('超级巨石投手')
    expect(armyTitleZh('Meteor Golem')).toBe('陨石戈仑')
  })

  it('组合名按 & / + 拆开翻译', () => {
    expect(armyTitleZh('Dragon & Dragon Rider')).toBe('飞龙 + 龙骑士')
    expect(armyTitleZh('Healer & Thrower')).toBe('天使 + 巨矛投手')
    expect(armyTitleZh('Balloon & Dragon')).toBe('气球兵 + 飞龙')
  })

  it('未收录的名字原样返回', () => {
    expect(armyTitleZh('Some New Army')).toBe('Some New Army')
  })
})
