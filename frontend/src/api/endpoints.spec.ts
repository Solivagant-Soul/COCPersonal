import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./request', () => ({ request: vi.fn() }))

import { request } from './request'
import {
  getArmies,
  getBases,
  getWarReportSeasonRankings,
  getWarReportSeasons,
  uploadBase,
} from './endpoints'

describe('War Report 接口封装', () => {
  beforeEach(() => vi.mocked(request).mockReset())

  it('赛季列表走 warreport/seasons', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [] }, meta: {} } as never)
    await getWarReportSeasons()
    expect(request).toHaveBeenCalledWith('/api/v1/rankings/warreport/seasons')
  })

  it('赛季榜用蛇形 page_size，并把 kind 放进路径', async () => {
    vi.mocked(request).mockResolvedValue({ data: {}, meta: {} } as never)
    await getWarReportSeasonRankings('2026-10-05', 'players', 2, 50)
    expect(request).toHaveBeenCalledWith(
      '/api/v1/rankings/warreport/seasons/2026-10-05/players',
      { params: { page: 2, page_size: 50 } },
    )
  })

  it('阵容接口固定 /api/v1/armies', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [] }, meta: {} } as never)
    await getArmies()
    expect(request).toHaveBeenCalledWith('/api/v1/armies')
  })
})

describe('阵型接口封装', () => {
  beforeEach(() => vi.mocked(request).mockReset())

  it('阵型列表固定 /api/v1/bases，参数 snake_case', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [], total: 0 }, meta: {} } as never)
    await getBases(18)
    expect(request).toHaveBeenCalledWith('/api/v1/bases', {
      params: { th_level: 18, page: 1, page_size: 24 },
    })
  })

  it('不传等级时不带 th_level', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [], total: 0 }, meta: {} } as never)
    await getBases()
    expect(request).toHaveBeenCalledWith('/api/v1/bases', {
      params: { page: 1, page_size: 24 },
    })
  })

  it('阵型上传带 Basic 头与 multipart', async () => {
    vi.mocked(request).mockResolvedValue({
      data: { id: 1, duplicated: false },
      meta: {},
    } as never)
    const file = new File([new Uint8Array([1])], 'a.png', { type: 'image/png' })

    await uploadBase({ title: 'x', layoutLink: 'https://e.com', image: file }, 'boss', 's3cret')

    const [path, opts] = vi.mocked(request).mock.calls[0]
    expect(path).toBe('/api/v1/admin/bases')
    expect(opts?.method).toBe('POST')
    expect(opts?.headers?.Authorization).toBe(`Basic ${btoa('boss:s3cret')}`)
    expect(opts?.data).toBeInstanceOf(FormData)
    const form = opts!.data as FormData
    expect(form.get('title')).toBe('x')
    expect(form.get('layout_link')).toBe('https://e.com')
    expect(form.get('image')).toBe(file)
  })

  it('非 ASCII 凭据按 UTF-8 编码再 base64（btoa 只吃 Latin-1）', async () => {
    vi.mocked(request).mockResolvedValue({ data: { id: 1 }, meta: {} } as never)

    await uploadBase({ title: 'x', layoutLink: 'https://e.com' }, '站长', '口令123')

    const [, opts] = vi.mocked(request).mock.calls[0]
    const header = opts!.headers!.Authorization
    const decoded = atob(header.replace(/^Basic /, ''))
    const bytes = Uint8Array.from(decoded, (char) => char.charCodeAt(0))
    expect(new TextDecoder().decode(bytes)).toBe('站长:口令123')
  })
})
