import { describe, expect, it } from 'vitest'

import {
  enumLabel,
  formatCompact,
  formatNumber,
  formatRelativeTime,
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
