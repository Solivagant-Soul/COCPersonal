import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import NotFound from './NotFound.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'query', component: { template: '<div/>' } },
    { path: '/:pathMatch(.*)*', name: 'notFound', component: NotFound },
  ],
})

async function mountAt(path: string) {
  await router.push(path)
  await router.isReady()
  const w = mount(NotFound, { global: { plugins: [router, ElementPlus] } })
  return w
}

describe('NotFound', () => {
  it('写出当前地址（方便用户看出自己打错了哪里）', async () => {
    const w = await mountAt('/no-such-page')

    expect(w.text()).toContain('页面不存在')
    expect(w.text()).toContain('/no-such-page')
  })

  it('提供回到查询页的入口', async () => {
    const w = await mountAt('/no-such-page')

    await w.find('button').trigger('click')
    // 导航是异步的（还要按需加载目标路由的组件），不等它就断言等于看运气
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('query')
  })
})
