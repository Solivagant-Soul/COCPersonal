import { describe, expect, it } from 'vitest'

import {
  enumLabel,
  formatBeijingTime,
  formatCompact,
  formatLeagueName,
  formatNumber,
  formatRelativeTime,
  formatShortBeijingTime,
  normalizeTag,
} from './format'

describe('formatNumber', () => {
  it('缺失值一律 -，不出现 undefined/null/NaN', () => {
    expect(formatNumber(null)).toBe('-')
    expect(formatNumber(undefined)).toBe('-')
    expect(formatNumber(Number.NaN)).toBe('-')
    expect(formatNumber(true)).toBe('-')
    expect(formatNumber('')).toBe('-')
  })

  it('千分位分隔', () => {
    expect(formatNumber(0)).toBe('0')
    expect(formatNumber(12345)).toBe('12,345')
    expect(formatNumber(-12345)).toBe('-12,345')
  })

  it('1e21 不得输出科学计数法', () => {
    expect(formatNumber(1e21)).toBe('1,000,000,000,000,000,000,000')
  })
})

describe('formatCompact', () => {
  it('小于 1 万原样千分位', () => {
    expect(formatCompact(9999)).toBe('9,999')
  })

  it('万 / 亿 缩写', () => {
    expect(formatCompact(12345)).toBe('1.2万')
    expect(formatCompact(150000000)).toBe('1.5亿')
  })

  it('超大数不得塌数量级', () => {
    const out = formatCompact(3e29)
    expect(out).not.toBe('3亿')
    expect(out.endsWith('亿')).toBe(true)
    expect(out.length).toBeGreaterThan(20)
  })
})

describe('normalizeTag', () => {
  it('全角＃/小写/无# 都归一化为 #大写', () => {
    expect(normalizeTag('＃8qu8j9j')).toBe('#8QU8J9J')
    expect(normalizeTag('8qu8j9j')).toBe('#8QU8J9J')
    expect(normalizeTag('  #8QU8J9J ')).toBe('#8QU8J9J')
  })

  it('纯字母的 3 位 tag 合法（后端正则就是 [0-9A-Z]{3,10}）', () => {
    expect(normalizeTag('abc')).toBe('#ABC')
  })

  it('非法输入返回 null（不发注定 400 的请求）', () => {
    expect(normalizeTag('ab')).toBeNull() // 太短
    expect(normalizeTag('abc!')).toBeNull() // 含非法字符
    expect(normalizeTag('')).toBeNull()
    expect(normalizeTag(null)).toBeNull()
    expect(normalizeTag(undefined)).toBeNull()
    expect(normalizeTag('#')).toBeNull()
  })
})

describe('formatRelativeTime', () => {
  it('1 分钟内与未来时间都是「刚刚」', () => {
    const base = Date.parse('2026-01-01T00:00:00Z')
    expect(formatRelativeTime('2026-01-01T00:00:00Z', base + 30000)).toBe('刚刚')
    expect(formatRelativeTime('2026-01-01T00:00:00Z', base - 30000)).toBe('刚刚')
  })

  it('缺失/非法时间返回 -', () => {
    expect(formatRelativeTime(null, Date.now())).toBe('-')
    expect(formatRelativeTime('not-a-date', Date.now())).toBe('-')
  })
})

describe('formatBeijingTime', () => {
  it('UTC 串换算成北京时间（+8），定宽到分钟', () => {
    expect(formatBeijingTime('2026-01-01T00:00:00Z')).toBe('2026-01-01 08:00')
    expect(formatBeijingTime('2026-10-23T20:23:11Z')).toBe('2026-10-24 04:23')
  })

  it('跨年/跨月不靠字符串截断', () => {
    // 2025-12-31T16:00Z 已经是北京时间 2026-01-01 00:00
    expect(formatBeijingTime('2025-12-31T16:00:00Z')).toBe('2026-01-01 00:00')
  })

  it('缺失/非法时间返回 -', () => {
    expect(formatBeijingTime(null)).toBe('-')
    expect(formatBeijingTime(undefined)).toBe('-')
    expect(formatBeijingTime('')).toBe('-')
    expect(formatBeijingTime('not-a-date')).toBe('-')
  })
})

describe('formatShortBeijingTime', () => {
  it('UTC 串换算成北京时间（+8），只到「月-日 时:分」', () => {
    expect(formatShortBeijingTime('2026-10-27T10:14:00Z')).toBe('10-27 18:14')
    expect(formatShortBeijingTime('2026-10-27T17:37:00Z')).toBe('10-28 01:37')
  })

  it('跨年也只显示月-日，不靠字符串截断', () => {
    // 2025-12-31T16:00Z 已经是北京时间 2026-01-01 00:00
    expect(formatShortBeijingTime('2025-12-31T16:00:00Z')).toBe('01-01 00:00')
  })

  it('缺失/非法时间返回 -', () => {
    expect(formatShortBeijingTime(null)).toBe('-')
    expect(formatShortBeijingTime(undefined)).toBe('-')
    expect(formatShortBeijingTime('')).toBe('-')
    expect(formatShortBeijingTime('not-a-date')).toBe('-')
  })
})

describe('enumLabel', () => {
  it('命中表格给中文', () => {
    expect(enumLabel('role', 'leader')).toBe('首领')
  })

  it('未知值原样返回，缺失返回 -', () => {
    expect(enumLabel('role', 'brandNew')).toBe('brandNew')
    expect(enumLabel('unknownGroup', 'x')).toBe('x')
    expect(enumLabel('role', null)).toBe('-')
  })
})

describe('formatLeagueName', () => {
  it('段位 + 罗马数字翻成中文', () => {
    expect(formatLeagueName('Legend I')).toBe('传奇 I')
    expect(formatLeagueName('Titan III')).toBe('泰坦 III')
  })

  it('档案里的 `X League` 写法也翻（`Legend League` → `传奇联赛`）', () => {
    expect(formatLeagueName('Legend League')).toBe('传奇联赛')
    expect(formatLeagueName('Bronze League II')).toBe('青铜 II')
    expect(formatLeagueName('Silver League')).toBe('白银联赛')
    expect(formatLeagueName('Unranked')).toBe('未定级')
  })

  it('其它形态原样返回，不猜', () => {
    expect(formatLeagueName('Builder Base Bronze I')).toBe('Builder Base Bronze I')
    expect(formatLeagueName('Builder Base Bronze')).toBe('Builder Base Bronze')
  })

  it('缺失值一律返回 -', () => {
    expect(formatLeagueName(null)).toBe('-')
    expect(formatLeagueName(undefined)).toBe('-')
    expect(formatLeagueName('')).toBe('-')
  })
})
