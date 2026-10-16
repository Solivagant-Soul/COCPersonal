import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import MainLayout from './MainLayout.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'query', component: { template: '<div/>' } },
    { path: '/rankings', name: 'rankings', component: { template: '<div/>' } },
  ],
})

describe('MainLayout', () => {
  it('导航只含查询与排行榜', () => {
    const w = mount(MainLayout, { global: { plugins: [router] } })
    const text = w.text()
    expect(text).toContain('查询')
    expect(text).toContain('排行榜')
    expect(text).not.toContain('投稿')
    expect(text).not.toContain('公告')
  })
})
