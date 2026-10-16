import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import TagInput from './TagInput.vue'

function mountInput() {
  return mount(TagInput, { global: { plugins: [ElementPlus] } })
}

describe('TagInput', () => {
  it('全角 / 小写 / 无 # 的标签归一化后再 emit', async () => {
    const w = mountInput()
    await w.find('input').setValue('＃8qu8j9j')
    await w.find('button').trigger('click')

    expect(w.emitted('submit')).toEqual([['#8QU8J9J']])
  })

  it('非法标签不 emit，就地提示（不发注定 400 的请求）', async () => {
    const w = mountInput()
    await w.find('input').setValue('ab')
    await w.find('button').trigger('click')

    expect(w.emitted('submit')).toBeUndefined()
    expect(w.text()).toContain('格式')
  })
})
