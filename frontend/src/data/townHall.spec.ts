import { describe, expect, it } from 'vitest'

import { townHallIcon } from './townHall'

describe('townHallIcon', () => {
  it('按等级拼素材路径', () => {
    expect(townHallIcon(1)).toBe('/pictures/townhall/TH1.png')
    expect(townHallIcon(15)).toBe('/pictures/townhall/TH15.png')
    expect(townHallIcon(18)).toBe('/pictures/townhall/TH18.png')
  })

  it('越界 / 非整数 / 缺失一律 null（不请求必然 404 的图）', () => {
    expect(townHallIcon(0)).toBeNull()
    expect(townHallIcon(19)).toBeNull()
    expect(townHallIcon(15.5)).toBeNull()
    expect(townHallIcon('16')).toBeNull()
    expect(townHallIcon(null)).toBeNull()
    expect(townHallIcon(undefined)).toBeNull()
  })
})
