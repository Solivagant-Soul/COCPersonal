import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SourceNote from './SourceNote.vue'

describe('SourceNote', () => {
  it('署名可见且链接到 warreport.app', () => {
    const w = mount(SourceNote)
    expect(w.text()).toContain('War Report')
    expect(w.text()).toContain('非 Supercell 官方')
    expect(w.find('a').attributes('href')).toBe('https://warreport.app')
    expect(w.find('a').attributes('rel')).toContain('noopener')
    // 新窗口打开：不开 target 会顶掉本站页面
    expect(w.find('a').attributes('target')).toBe('_blank')
  })

  it('整句署名一处不漏（这是使用条件，不是装饰）', () => {
    const w = mount(SourceNote)
    // 拆开断言容易只改一半：整句钉住。改文案时这条会失败，逼人回来看 §12。
    expect(w.text().replace(/\s+/g, '')).toBe(
      '数据来源：WarReport·非Supercell官方，未获Supercell背书',
    )
  })

  it('只有一个外链 —— 多出来的锚点没人看，还会把署名拆散', () => {
    const w = mount(SourceNote)
    expect(w.findAll('a')).toHaveLength(1)
  })
})
