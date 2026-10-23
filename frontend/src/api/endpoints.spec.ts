import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./request', () => ({ request: vi.fn() }))

import { request } from './request'
import {
  getArmies,
  getWarReportSeasonRankings,
  getWarReportSeasons,
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
