import { beforeEach, describe, expect, it } from 'vitest'

import {
  HISTORY_KEY,
  HISTORY_LIMIT,
  addHistory,
  clearHistory,
  readHistory,
  removeHistory,
} from './searchHistory'

describe('searchHistory', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('addHistory', () => {
    it('记下的条目带标签、类型与时间戳', () => {
      addHistory('#ABC', 'player')

      const entries = readHistory()
      expect(entries).toHaveLength(1)
      expect(entries[0].tag).toBe('#ABC')
      expect(entries[0].kind).toBe('player')
      expect(typeof entries[0].at).toBe('number')
    })

    it('同一个标签再查一次不产生重复，而是移到最前', () => {
      addHistory('#AAA', 'player')
      addHistory('#BBB', 'player')
      addHistory('#AAA', 'player')

      const entries = readHistory()
      expect(entries.map((e) => e.tag)).toEqual(['#AAA', '#BBB'])
    })

    it('同一标签换了类型算新条目', () => {
      addHistory('#AAA', 'player')
      addHistory('#AAA', 'clan')

      const entries = readHistory()
      expect(entries).toHaveLength(2)
      expect(entries.map((e) => e.kind)).toEqual(['clan', 'player'])
    })

    it('超过上限时丢掉最旧的', () => {
      for (let i = 0; i < HISTORY_LIMIT + 5; i++) {
        addHistory(`#T${i}`.padEnd(4, 'X'), 'player')
      }

      const entries = readHistory()
      expect(entries).toHaveLength(HISTORY_LIMIT)
      // 最新的一条必须在最前
      expect(entries[0].tag).toBe(`#T${HISTORY_LIMIT + 4}`.padEnd(4, 'X'))
    })

    it('localStorage 不可用时不抛异常（隐私模式等）', () => {
      const original = Storage.prototype.setItem
      Storage.prototype.setItem = () => {
        throw new Error('QuotaExceededError')
      }
      try {
        expect(() => addHistory('#ABC', 'player')).not.toThrow()
      } finally {
        Storage.prototype.setItem = original
      }
    })
  })

  describe('readHistory', () => {
    it('没有记录时返回空数组', () => {
      expect(readHistory()).toEqual([])
    })

    it('存储里的 JSON 损坏时返回空数组，不抛异常', () => {
      localStorage.setItem(HISTORY_KEY, '{ 不是 JSON')
      expect(readHistory()).toEqual([])
    })

    it('存储里的结构不对时逐条丢弃合法的部分', () => {
      localStorage.setItem(
        HISTORY_KEY,
        JSON.stringify([
          { tag: '#AAA', kind: 'player', at: 1 },
          { tag: 123, kind: 'player', at: 2 },
          { tag: '#CCC', kind: 'unknown', at: 3 },
          null,
        ]),
      )

      const entries = readHistory()
      expect(entries.map((e) => e.tag)).toEqual(['#AAA'])
    })

    it('不是数组时返回空数组', () => {
      localStorage.setItem(HISTORY_KEY, '"字符串"')
      expect(readHistory()).toEqual([])
    })
  })

  describe('removeHistory / clearHistory', () => {
    it('removeHistory 只删指定条目', () => {
      addHistory('#AAA', 'player')
      addHistory('#BBB', 'player')

      removeHistory('#AAA', 'player')

      expect(readHistory().map((e) => e.tag)).toEqual(['#BBB'])
    })

    it('removeHistory 不影响同标签但不同类型的条目', () => {
      addHistory('#AAA', 'player')
      addHistory('#AAA', 'clan')

      removeHistory('#AAA', 'player')

      expect(readHistory().map((e) => e.kind)).toEqual(['clan'])
    })

    it('clearHistory 清空全部', () => {
      addHistory('#AAA', 'player')
      addHistory('#BBB', 'clan')

      clearHistory()

      expect(readHistory()).toEqual([])
    })
  })
})
