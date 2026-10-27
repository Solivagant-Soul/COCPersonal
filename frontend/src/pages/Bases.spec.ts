import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { installElementPlus } from '../plugins/element'
import Bases from './Bases.vue'

describe('Bases', () => {
  it('渲染阵型占位卡片', () => {
    const w = mount(Bases, { global: { plugins: [{ install: installElementPlus }] } })

    expect(w.text()).toContain('阵型')
    expect(w.text()).toContain('阵型功能开发中，敬请期待')
  })

  it('用与其他页签一致的卡片外壳（标题在卡内，且只有一张卡）', () => {
    const w = mount(Bases, { global: { plugins: [{ install: installElementPlus }] } })

    expect(w.findAll('.page-card')).toHaveLength(1)
    expect(w.find('.page-card .page-card__title').text()).toBe('阵型')
  })
})
