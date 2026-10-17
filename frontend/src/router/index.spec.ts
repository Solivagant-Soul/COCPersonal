import { beforeEach, describe, expect, it } from 'vitest'

import router, { APP_TITLE } from './index'

describe('路由标题与兜底路由', () => {
  beforeEach(() => {
    document.title = ''
  })

  it('每个路由都把标题写成「页面名 · 基名」', async () => {
    await router.push('/rankings')
    expect(document.title).toBe(`排行榜 · ${APP_TITLE}`)

    await router.push('/')
    expect(document.title).toBe(`查询 · ${APP_TITLE}`)

    await router.push('/players/%239QJ8L0')
    expect(document.title).toBe(`玩家详情 · ${APP_TITLE}`)

    await router.push('/clans/%232PP')
    expect(document.title).toBe(`部落详情 · ${APP_TITLE}`)
  })

  it('不存在的地址落到兜底页而不是空 router-view', async () => {
    await router.push('/no-such-page')

    expect(router.currentRoute.value.name).toBe('notFound')
    expect(document.title).toBe(`页面不存在 · ${APP_TITLE}`)
  })
})
