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
  })
})
