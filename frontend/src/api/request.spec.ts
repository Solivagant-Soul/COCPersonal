import MockAdapter from 'axios-mock-adapter'
import { beforeEach, describe, expect, it } from 'vitest'

import { apiClient, request } from './request'

let mock: MockAdapter

beforeEach(() => {
  mock = new MockAdapter(apiClient)
})

describe('request', () => {
  it('成功：解开信封并把 meta 蛇形转驼峰', async () => {
    mock.onGet('/api/v1/players/%23A').reply(200, {
      data: { tag: '#A' },
      meta: { cache: 'HIT', fetched_at: 't', age_seconds: 0, ttl_seconds: 60 },
    })

    const res = await request<{ tag: string }>('/api/v1/players/%23A')

    expect(res.data.tag).toBe('#A')
    expect(res.meta).toEqual({
      cache: 'HIT',
      fetchedAt: 't',
      ageSeconds: 0,
      ttlSeconds: 60,
    })
  })

  it('age_seconds=0 保留为 0，不因 falsy 变 null', async () => {
    mock.onGet('/x').reply(200, { data: {}, meta: { cache: 'MISS', age_seconds: 0 } })

    const res = await request('/x')

    expect(res.meta.ageSeconds).toBe(0)
  })

  it('STALE 不特判：照常 resolve', async () => {
    mock.onGet('/x').reply(200, { data: { ok: 1 }, meta: { cache: 'STALE' } })

    const res = await request('/x')

    expect(res.meta.cache).toBe('STALE')
    expect((res.data as { ok: number }).ok).toBe(1)
  })

  it('非 2xx 且有 error 体：透传后端 code', async () => {
    mock.onGet('/x').reply(404, {
      error: { code: 'CLAN_NOT_FOUND', message: '部落不存在' },
    })

    await expect(request('/x')).rejects.toMatchObject({
      code: 'CLAN_NOT_FOUND',
      status: 404,
    })
  })

  it('非 2xx 且无 error 体：4xx→BAD_REQUEST，5xx→UPSTREAM_UNAVAILABLE', async () => {
    mock.onGet('/a').reply(400, 'plain')
    await expect(request('/a')).rejects.toMatchObject({
      code: 'BAD_REQUEST',
      status: 400,
    })

    mock.onGet('/b').reply(502, 'plain')
    await expect(request('/b')).rejects.toMatchObject({
      code: 'UPSTREAM_UNAVAILABLE',
      status: 502,
    })
  })

  it('2xx 但 body 是数组：BAD_RESPONSE', async () => {
    mock.onGet('/x').reply(200, [1, 2, 3])

    await expect(request('/x')).rejects.toMatchObject({ code: 'BAD_RESPONSE' })
  })

  it('2xx 但 meta 缺失：BAD_RESPONSE（不白屏）', async () => {
    mock.onGet('/x').reply(200, { data: {} })

    await expect(request('/x')).rejects.toMatchObject({ code: 'BAD_RESPONSE' })
  })

  it('网络失败：NETWORK_ERROR, status 0', async () => {
    mock.onGet('/x').networkError()

    await expect(request('/x')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      status: 0,
    })
  })
})
