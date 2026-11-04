import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./request', () => ({ request: vi.fn() }))

import { request } from './request'
import {
  getArmies,
  getBases,
  uploadBase,
  getWarReportSeasonRankings,
  getWarReportSeasons,
} from './endpoints'

describe('War Report 鎺ュ彛灏佽', () => {
  beforeEach(() => vi.mocked(request).mockReset())

  it('璧涘鍒楄〃璧?warreport/seasons', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [] }, meta: {} } as never)
    await getWarReportSeasons()
    expect(request).toHaveBeenCalledWith('/api/v1/rankings/warreport/seasons')
  })

  it('璧涘姒滅敤铔囧舰 page_size锛屽苟鎶?kind 鏀捐繘璺緞', async () => {
    vi.mocked(request).mockResolvedValue({ data: {}, meta: {} } as never)
    await getWarReportSeasonRankings('2026-10-05', 'players', 2, 50)
    expect(request).toHaveBeenCalledWith(
      '/api/v1/rankings/warreport/seasons/2026-10-05/players',
      { params: { page: 2, page_size: 50 } },
    )
  })

  it('闃靛鎺ュ彛鍥哄畾 /api/v1/armies', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [] }, meta: {} } as never)
    await getArmies()
    expect(request).toHaveBeenCalledWith('/api/v1/armies')
  })
})

describe('闃靛瀷鎺ュ彛灏佽', () => {
  beforeEach(() => vi.mocked(request).mockReset())

  it('闃靛瀷鍒楄〃鍥哄畾 /api/v1/bases锛屽弬鏁?snake_case', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [], total: 0 }, meta: {} } as never)
    await getBases(18)
    expect(request).toHaveBeenCalledWith('/api/v1/bases', {
      params: { th_level: 18, page: 1, page_size: 24 },
    })
  })

  it('涓嶄紶绛夌骇鏃朵笉甯?th_level', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [], total: 0 }, meta: {} } as never)
    await getBases()
    expect(request).toHaveBeenCalledWith('/api/v1/bases', {
      params: { page: 1, page_size: 24 },
    })
  })

  it('闃靛瀷涓婁紶甯?Basic 澶翠笌 multipart', async () => {
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
})
