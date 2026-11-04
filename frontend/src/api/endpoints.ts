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

/** 联赛（层级）：`id` 必有，`name` / `iconUrls` 由后端尽量补齐。 */
export interface LeagueRef {
  id?: number | null
  name?: string | null
  iconUrls?: Record<string, string> | null
}

/** 兵种 / 法术 / 英雄的练度行。上游只给英文名，中文名映射在前端素材表里。 */
export interface UnitLevelRow {
  name: string
  level?: number | null
  maxLevel?: number | null
  village?: string | null
  [key: string]: unknown
}

/** 传奇杯统计里的单个赛季。 */
export interface LegendSeason {
  id?: string | null
  rank?: number | null
  trophies?: number | null
}

/**
 * 一支队伍里的子列表。后端只透传官方认识的槽位（troops / spells / heroes /
 * pets / equipment），前端只用到前三组的图标。
 */
export interface BattleArmy {
  troops?: UnitLevelRow[] | null
  spells?: UnitLevelRow[] | null
  heroes?: UnitLevelRow[] | null
  pets?: UnitLevelRow[] | null
  equipment?: UnitLevelRow[] | null
}

/** `attack` = 我们打的，`defense` = 别人打我们。 */
export type BattleKind = 'attack' | 'defense'

/** 官方 battlelog 的一条战报（后端已归一化，按时间倒序）。 */
export interface PlayerBattle {
  timestamp?: string | null
  kind: BattleKind
  stars?: number | null
  destructionPercentage?: number | null
  opponent?: { tag?: string | null; name?: string | null } | null
  army?: BattleArmy | null
}

export interface PlayerBattlesPage {
  items: PlayerBattle[]
}

export interface PlayerProfile {
  tag: string
  name?: string | null
  expLevel?: number | null
  trophies?: number | null
  bestTrophies?: number | null
  builderBaseTrophies?: number | null
  townHallLevel?: number | null
  townHallWeaponLevel?: number | null
  builderHallLevel?: number | null
  warStars?: number | null
  attackWins?: number | null
  defenseWins?: number | null
  donations?: number | null
  donationsReceived?: number | null
  clan?: ClanRef | null
  role?: string | null
  league?: LeagueRef | null
  builderBaseLeague?: { id?: number | null; name?: string | null } | null
  achievements?: unknown[] | null
  labels?: unknown[] | null
  legendStatistics?: Record<string, unknown> | null
  troops?: UnitLevelRow[] | null
  heroes?: UnitLevelRow[] | null
  spells?: UnitLevelRow[] | null
  heroEquipment?: UnitLevelRow[] | null
  [key: string]: unknown
}

export interface ClanMemberRow {
  tag: string
  name?: string | null
  role?: string | null
  expLevel?: number | null
  townHallLevel?: number | null
  trophies?: number | null
  builderBaseTrophies?: number | null
  clanRank?: number | null
  previousClanRank?: number | null
  donations?: number | null
  donationsReceived?: number | null
  /** 联赛层级：后端从 league_tiers 维表补名字与图标，维表没数据时为 null。 */
  league?: LeagueRef | null
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

/** 榜单针对的实体。与 `RankingKind` 取值域相同，只是借一个更贴切的语义名。 */
export type RankingEntity = RankingKind

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

/**
 * 榜单里可展示的指标列。**用联合类型而不是裸 string** —— 这样
 * `row[col.prop]` 的索引是类型安全的，`RankingTable` 里不会因为
 * 指标名写错而在运行时静默显示空白。
 */
export type RankingMetric =
  | 'points'
  | 'members'
  | 'clanLevel'
  | 'trophies'
  | 'expLevel'
  | 'builderBaseTrophies'

export interface RankingsPage {
  items: RankingRow[]
  total: number
  kind: string
}

/**
 * War Report 的一个赛季快照。`fetchedAt` 是该赛季数据被抓取的时间，
 * 后端在没有记录时给 null。
 */
export interface WarReportSeason {
  seasonId: string
  players: number
  clans: number
  fetchedAt: string | null
}

/** 阵容榜的一行，按 `position` 排好序返回。 */
export interface ArmyRow {
  position: number
  name: string
  canonicalKey: string
  armyShareCode: string
  armyLink: string
  playerCount: number
  useCount: number
  percentage: number
  averageStars: number
  averageDestruction: number
}

export function getPlayer(tag: string): Promise<Envelope<PlayerProfile>> {
  return request<PlayerProfile>(`/api/v1/players/${encodeURIComponent(tag)}`)
}

/** 最近的传奇联赛战报。非传奇玩家返回空列表（不是错误）。 */
export function getPlayerBattles(tag: string): Promise<Envelope<PlayerBattlesPage>> {
  return request<PlayerBattlesPage>(
    `/api/v1/players/${encodeURIComponent(tag)}/battles`,
  )
}

export function getClan(tag: string): Promise<Envelope<ClanDetail>> {
  return request<ClanDetail>(`/api/v1/clans/${encodeURIComponent(tag)}`)
}

/** 部落成员。官方单个部落上限 50 人，默认一页取全。 */
export function getClanMembers(
  tag: string,
  pageSize = 50,
): Promise<Envelope<ClanMemberRow[]>> {
  return request<ClanMemberRow[]>(
    `/api/v1/clans/${encodeURIComponent(tag)}/members`,
    { params: { page: 1, page_size: pageSize } },
  )
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
  kind: RankingEntity,
  locationId: number = GLOBAL_LOCATION_ID,
  page = 1,
  pageSize = 20,
): Promise<Envelope<RankingsPage>> {
  return request<RankingsPage>(`/api/v1/rankings/${kind}`, {
    // 注意：HTTP 参数是 snake_case 的 page_size
    params: { locationId, page, page_size: pageSize },
  })
}

/** 有 War Report 赛季快照的赛季列表，新的在前（后端最多给 3 个）。 */
export function getWarReportSeasons(): Promise<Envelope<{ items: WarReportSeason[] }>> {
  return request<{ items: WarReportSeason[] }>('/api/v1/rankings/warreport/seasons')
}

/** 某个赛季快照的榜单，形状与线上榜单一致（`items` / `total` / `kind`）。 */
export function getWarReportSeasonRankings(
  snapshot: string,
  entity: RankingEntity,
  page = 1,
  pageSize = 20,
): Promise<Envelope<RankingsPage>> {
  return request<RankingsPage>(
    `/api/v1/rankings/warreport/seasons/${snapshot}/${entity}`,
    // 注意：HTTP 参数是 snake_case 的 page_size
    { params: { page, page_size: pageSize } },
  )
}

export function getArmies(): Promise<Envelope<{ items: ArmyRow[] }>> {
  return request<{ items: ArmyRow[] }>('/api/v1/armies')
}

/** 一条阵型（基地布局）。链接与图片至少有一个，图片是 `/media/...` 相对 URL。 */
export interface BaseLayoutItem {
  id: number
  title: string
  thLevel: number | null
  layoutLink: string | null
  imagePath: string | null
  sourceUrl: string | null
  sourceSite: string | null
  createdAt: string | null
}

export interface BasesPage {
  items: BaseLayoutItem[]
  total: number
}

/** 上传表单的输入。`image` 与 `layoutLink` 至少给一个。 */
export interface UploadBaseInput {
  title: string
  thLevel?: number | null
  layoutLink?: string | null
  image?: File | null
  sourceUrl?: string | null
  sourceSite?: string | null
}

/** 阵型列表。`thLevel` 为 null 表示不筛等级。 */
export function getBases(
  thLevel: number | null = null,
  page = 1,
  pageSize = 24,
): Promise<Envelope<BasesPage>> {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (thLevel !== null) params.th_level = thLevel
  return request<BasesPage>('/api/v1/bases', { params })
}

/**
 * 管理员上传一条阵型，上传即发布。
 *
 * 鉴权是 HTTP Basic，凭据来自环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，
 * 由表单里手工填（不写进前端构建产物）。
 */
export function uploadBase(
  input: UploadBaseInput,
  username: string,
  password: string,
): Promise<Envelope<BaseLayoutItem & { duplicated: boolean }>> {
  const form = new FormData()
  form.append('title', input.title)
  if (input.thLevel !== undefined && input.thLevel !== null) {
    form.append('th_level', String(input.thLevel))
  }
  if (input.layoutLink) form.append('layout_link', input.layoutLink)
  if (input.sourceUrl) form.append('source_url', input.sourceUrl)
  if (input.sourceSite) form.append('source_site', input.sourceSite)
  if (input.image) form.append('image', input.image)

  return request<BaseLayoutItem & { duplicated: boolean }>('/api/v1/admin/bases', {
    method: 'POST',
    data: form,
    headers: { Authorization: `Basic ${btoa(`${username}:${password}`)}` },
  })
}
