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
})
