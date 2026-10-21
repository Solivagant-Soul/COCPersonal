import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import type { RankingRow } from '../api/endpoints'
import RankingTable from './RankingTable.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/players/:tag', name: 'player', component: { template: '<div/>' } },
    { path: '/clans/:tag', name: 'clan', component: { template: '<div/>' } },
  ],
})

function row(over: Partial<RankingRow>): RankingRow {
  return {
    rank: 1,
    tag: '#AAA',
    name: 'AAA',
    ...over,
  }
}

function mountTable(rows: RankingRow[], kind: 'clans' | 'players' = 'clans') {
  return mount(RankingTable, {
    props: { rows, kind },
    global: { plugins: [router] },
  })
}

describe('RankingTable', () => {
  it('空数据显示空态，不是错误', () => {
    const w = mountTable([])
    expect(w.text()).toContain('暂无数据')
    expect(w.find('.ranking-card').exists()).toBe(false)
  })

  it('渲染成卡片列表，每行一张卡', () => {
    const w = mountTable([row({ rank: 1 }), row({ rank: 2, tag: '#BBB', name: 'BBB' })])
    const cards = w.findAll('.ranking-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('AAA')
  })

  it('名次梯级徽章：1 名 OP、2-3 名 S、4-10 名 A', () => {
    const w = mountTable([
      row({ rank: 1, tag: '#A' }),
      row({ rank: 2, tag: '#B' }),
      row({ rank: 9, tag: '#C' }),
    ])
    const tiers = w.findAll('.ranking-card__tier').map((t) => t.text())
    expect(tiers).toEqual(['OP', 'S', 'A'])
  })

  it('名次涨跌：previousRank 比现在大 = 上升', () => {
    const w = mountTable([row({ rank: 3, previousRank: 5 })])
    const delta = w.find('.ranking-card__delta')
    expect(delta.text()).toContain('▲')
    expect(delta.classes()).toContain('delta-up')
  })

  it('名次下跌用红色', () => {
    const w = mountTable([row({ rank: 5, previousRank: 3 })])
    const delta = w.find('.ranking-card__delta')
    expect(delta.text()).toContain('▼')
    expect(delta.classes()).toContain('delta-down')
  })

  it('新上榜（previousRank 为 null）不显示箭头', () => {
    const w = mountTable([row({ rank: 1, previousRank: null })])
    // 不该显示「跌到底」或任何箭头
    expect(w.find('.ranking-card__delta').text()).toBe('')
  })

  it('玩家榜的链接指向玩家详情，部落榜指向部落详情', () => {
    const w = mountTable([row({ tag: '#AAA' })], 'players')
    expect(w.find('.ranking-card__name').attributes('href')).toBe('/players/%23AAA')

    const w2 = mountTable([row({ tag: '#AAA' })], 'clans')
    expect(w2.find('.ranking-card__name').attributes('href')).toBe('/clans/%23AAA')
  })

  it('部落榜显示积分/成员/等级，玩家榜显示奖杯/等级', () => {
    const clan = mountTable([row({ rank: 1 })], 'clans')
    expect(clan.text()).toContain('积分')
    expect(clan.text()).toContain('成员')
    expect(clan.text()).toContain('等级')

    const player = mountTable([row({ rank: 1 })], 'players')
    expect(player.text()).toContain('奖杯')
    expect(player.text()).not.toContain('成员')
  })
})
