/**
 * 后端接口的 typed 封装。**只有这里知道 URL 与查询参数名**，页面不拼字符串。
 *
 * 注意两个后端约定：
 *   - `locationId` 是别名（Python 侧 `alias="locationId"`），保持不变；
 *   - 分页参数在 HTTP 上是 `page_size`（蛇形），不是 `pageSize`。
 */

import { request, type Envelope } from './request'

export interface ClanRef {
  tag: string
  name?: string | null
}

export interface PlayerProfile {
  tag: string
  name?: string | null
  expLevel?: number | null
  trophies?: number | null
  bestTrophies?: number | null
  builderBaseTrophies?: number | null
  townHallLevel?: number | null
  builderHallLevel?: number | null
  warStars?: number | null
  attackWins?: number | null
  defenseWins?: number | null
  clan?: ClanRef | null
  role?: string | null
  league?: { id?: number | null } | null
  [key: string]: unknown
}

export interface ClanMemberRow {
  tag: string
  name?: string | null
  role?: string | null
  expLevel?: number | null
  trophies?: number | null
  donations?: number | null
  clanRank?: number | null
  [key: string]: unknown
}

export interface ClanDetail {
  tag: string
  name?: string | null
  description?: string | null
  clanLevel?: number | null
  clanPoints?: number | null
  clanVersusPoints?: number | null
  requiredTrophies?: number | null
  warFrequency?: string | null
  warWinStreak?: number | null
  warWins?: number | null
  warTies?: number | null
  warLosses?: number | null
  isWarLogPublic?: boolean | null
  members?: number | null
  location?: { id?: number | null; name?: string | null } | null
  badgeUrls?: Record<string, string> | null
  memberList?: ClanMemberRow[]
  [key: string]: unknown
}

export interface Location {
  id: number
  name: string
  countryCode?: string | null
}

export interface LocationsPage {
  items: Location[]
  total: number
}

/**
 * 榜单类型，与后端 `RankingKind` 的字符串取值一致。
 *
 * 只有部落榜与玩家榜 —— 都城榜 / 部落基地榜 / 玩家基地榜已随「只收全服 +
 * 只收部落与玩家数据」的需求一并移除（后端路由返回 404）。
 */
export type RankingKind = 'clans' | 'players'

export interface RankingRow {
  rank: number
  previousRank?: number | null
  tag: string
  name?: string | null
  clanTag?: string | null
  clanName?: string | null
  clanLevel?: number | null
  trophies?: number | null
  builderBaseTrophies?: number | null
  points?: number | null
  members?: number | null
  expLevel?: number | null
  attackWins?: number | null
  defenseWins?: number | null
}

export interface RankingsPage {
  items: RankingRow[]
  total: number
  kind: string
}

export function getPlayer(tag: string): Promise<Envelope<PlayerProfile>> {
  return request<PlayerProfile>(`/api/v1/players/${encodeURIComponent(tag)}`)
}

export function getClan(tag: string): Promise<Envelope<ClanDetail>> {
  return request<ClanDetail>(`/api/v1/clans/${encodeURIComponent(tag)}`)
}

export function getLocations(): Promise<Envelope<LocationsPage>> {
  return request<LocationsPage>('/api/v1/locations')
}

/**
 * 全服的地区 ID。官方地区 ID 的高位段是 32000000，Global 是 32000000
 * （注意它的 isCountry 是 false —— 靠「国家」过滤找不到全服）。
 */
export const GLOBAL_LOCATION_ID = 32000000

export function getRankings(
  kind: RankingKind,
  locationId: number = GLOBAL_LOCATION_ID,
  page = 1,
  pageSize = 20,
): Promise<Envelope<RankingsPage>> {
  return request<RankingsPage>(`/api/v1/rankings/${kind}`, {
    // 注意：HTTP 参数是 snake_case 的 page_size
    params: { locationId, page, page_size: pageSize },
  })
}
