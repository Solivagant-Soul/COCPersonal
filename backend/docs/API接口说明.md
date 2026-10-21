# Clash of Clans API 接口说明文档

> 官方文档地址：<https://developer.clashofclans.com/#/documentation>
> 文档整理日期：2026-09-30

---

## 目录

- [1. 概述](#1-概述)
- [2. 接入准备](#2-接入准备)
- [3. 认证与鉴权](#3-认证与鉴权)
- [4. 请求规范](#4-请求规范)
- [5. 响应格式与状态码](#5-响应格式与状态码)
- [6. 错误码参考](#6-错误码参考)
- [7. 通用数据结构](#7-通用数据结构)
- [8. 接口总览](#8-接口总览)
- [9. 接口详情](#9-接口详情)
  - [9.1 部落 Clans](#91-部落-clans)
  - [9.2 部落战与联赛战 Clan Wars](#92-部落战与联赛战-clan-wars)
  - [9.3 玩家 Players](#93-玩家-players)
  - [9.4 联赛 Leagues](#94-联赛-leagues)
  - [9.5 地区与排行榜 Locations](#95-地区与排行榜-locations)
  - [9.6 标签 Labels](#96-标签-labels)
  - [9.7 黄金令牌 Gold Pass](#97-黄金令牌-gold-pass)
- [10. 枚举值参考](#10-枚举值参考)
- [11. 调用示例](#11-调用示例)
- [12. 附录：社区库中的非公开接口](#12-附录社区库中的非公开接口)

---

## 1. 概述

Clash of Clans API 是 Supercell 官方提供的 RESTful 接口，用于**近实时**读取游戏相关数据，包括：

- 部落搜索、部落详情、成员列表
- 部落战日志、当前部落战、部落对战联赛（CWL）
- 玩家档案、成就、部队/英雄/法术/装备等级
- 全球与地区排行榜（玩家 / 部落 / 都城 / 建筑大师基地）
- 联赛层级、战争联赛、都城联赛、建筑大师基地联赛
- 标签、地区、黄金令牌赛季

> **注意**：该 API 为**只读**接口（唯一例外是 `verifytoken` 校验接口），无法通过它修改游戏内数据。

### 基本信息

| 项目 | 值 |
| --- | --- |
| 接口根地址（Base URL） | `https://api.clashofclans.com/v1` |
| 开发者站点 API | `https://developer.clashofclans.com/api` |
| 协议 | HTTPS（**仅支持 HTTPS**） |
| 请求方法 | `GET` / `POST` |
| 响应格式 | JSON（UTF-8 编码） |
| 认证方式 | Bearer Token（JWT） |
| 静态资源 CDN | `https://api-assets.clashofclans.com` |

---

## 2. 接入准备

### 2.1 创建开发者账号

1. 访问 <https://developer.clashofclans.com/>
2. 点击 **Register** 注册账号（需邮箱验证）
3. 登录后进入 **My Account** 页面

### 2.2 创建 API Key

在 **My Account** 页面创建 API Key：

| 字段 | 说明 |
| --- | --- |
| **Name** | Key 的名称，建议为每个应用创建独立 Key |
| **Description** | 用途描述（可选） |
| **IP Addresses** | **必填**。允许调用该 API 的 IP 白名单，可填多个，支持 CIDR 网段 |

> ⚠️ **IP 白名单是最常见的踩坑点**
>
> - Key 与 IP 强绑定，从白名单外的 IP 调用会返回 `403 accessDenied.invalidIp`
> - 家用宽带 / 云主机的**公网出口 IP** 才是需要填写的地址
> - 服务器 IP 变更（如重启云主机、切换网络）后必须回到站点更新 Key
> - 官方建议：**每个应用使用独立的 Key**，避免互相挤占速率额度
> - 账号下 Key 数量有上限，超出时需先删除不再使用的 Key

### 2.3 获取 Token

创建完成后，站点会返回一个 **JWT Token**（形如 `eyJ0eXAiOiJKV1Qi...`）。
该 Token 即后续所有请求所需的凭证，**请妥善保管，不要提交到公开代码仓库**。

---

## 3. 认证与鉴权

### 3.1 请求头

所有请求都必须在 HTTP Header 中携带 JWT：

```http
Authorization: Bearer <你的_API_Token>
```

示例：

```bash
curl -H "Authorization: Bearer eyJ0eXAiOiJKV1Qi..." \
     "https://api.clashofclans.com/v1/clans/%232PP"
```

### 3.2 鉴权要点

- Token 是 **JWT**（JSON Web Token），自带签名与有效期，服务端不提供刷新接口，过期后需重新创建
- Token 同时绑定**速率限制**与**IP 白名单**，任一不满足都会导致调用失败
- Token 需要放在**服务端**使用。官方明确说明：由于 IP 限制，你需要一台 Web 服务器来中转请求，**不应把 Token 直接下发到客户端**（小程序 / 前端 / 移动端）

> **小程序 / 前端场景的推荐架构**
>
> ```
> 小程序 / 前端  ──►  你自己的后端服务  ──►  api.clashofclans.com
>   （无 Token）      （持有 Token + 固定 IP）    （校验 Token + IP）
> ```
>
> 后端可在此基础上做缓存（部落战 / 玩家档案变化慢，缓存 1–5 分钟通常足够），
> 既能规避 IP 白名单问题，也能大幅降低触发 429 的概率。

---

## 4. 请求规范

### 4.1 资源标识（Tag）编码

部落标签、玩家标签、战争标签均以 `#` 开头，例如 `#2PP`、`#9QJ8L0`。

由于 `#` 在 URL 中是片段标识符，**必须进行 URL 编码**：

| 原始 | 编码后 |
| --- | --- |
| `#2PP` | `%232PP` |
| `#9QJ8L0` | `%239QJ8L0` |

```http
✅ GET /v1/clans/%232PP
❌ GET /v1/clans/#2PP      ← 错误，会被解析为 URL 片段
```

### 4.2 时间格式

响应中的时间字段统一为 **ISO 8601 UTC** 格式，精度到毫秒：

```
2024-01-15T08:30:00.000Z
```

### 4.3 分页

所有列表类接口均支持游标分页：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `limit` | int | 单页返回条数，取值 `1`–`50`，默认值随接口而异（见各接口说明） |
| `after` | string | 游标：获取该游标**之后**的数据（向后翻页） |
| `before` | string | 游标：获取该游标**之前**的数据（向前翻页） |

响应中会返回 `paging.cursors`：

```json
{
  "items": [ ... ],
  "paging": {
    "cursors": {
      "after": "eyJvZmZzZXQiOjUwfQ==",
      "before": "eyJvZmZzZXQiOjB9"
    }
  }
}
```

翻页时将 `cursors.after` 的值作为下一次请求的 `after` 参数传入即可。

### 4.4 速率限制

- 官方对每个 **API Token**（结合来源 IP）限制请求频率
- 超出阈值时返回 **HTTP 429**，响应体 `reason` 为 `requestThrottled`
- 社区实践中通常以 **10 次/秒** 作为安全阈值（不同 Key 之间额度独立）

**应对建议：**

1. 客户端做**全局限流**（令牌桶 / 信号量），确保并发不超过阈值
2. 遇到 429 时**指数退避重试**（如 1s → 2s → 4s）
3. 对变化缓慢的资源做**缓存**：
   - 部落 / 玩家档案：缓存 1–5 分钟
   - 部落战：准备期 / 战斗期建议 1–2 分钟
   - 联赛层级、地区、标签等静态数据：缓存数小时至数天
4. 批量查询多个部落时，在服务端**串行 + 间隔**调度，而非并发轰炸

---

## 5. 响应格式与状态码

所有响应均为 **UTF-8 编码的 JSON**，使用标准 HTTP 状态码表示成功与失败。

### 成功响应

```json
{
  "tag": "#2PP",
  "name": "示例部落",
  "clanLevel": 15
}
```

### 错误响应

```json
{
  "reason": "accessDenied",
  "message": "Missing authorization"
}
```

| 字段 | 说明 |
| --- | --- |
| `reason` | 机器可读的错误原因标识（枚举，见下表） |
| `message` | 人类可读的错误描述 |

### HTTP 状态码

| 状态码 | 含义 | 对应 `reason` |
| --- | --- | --- |
| `200` | 请求成功 | — |
| `400` | 请求参数错误 | `badRequest` |
| `403` | 鉴权失败 / 无权限 | `accessDenied`、`accessDenied.invalidIp`、`privateWarLog` |
| `404` | 资源不存在 | `notFound`、`notInWar` |
| `429` | 请求过于频繁（限流） | `requestThrottled` |
| `500` | 服务端内部错误 | `unknownException` |
| `503` | 服务维护中 | `inMaintenance` |
| `504` | 请求被中断 | `requestAborted` |

---

## 6. 错误码参考

| `reason` | HTTP | 说明 | 处理建议 |
| --- | --- | --- | --- |
| `badRequest` | 400 | 参数不合法（如 limit 超范围、标签格式错误） | 检查参数，修正后重试 |
| `accessDenied` | 403 | 缺少或错误的凭证 | 检查 `Authorization` 头是否携带且格式正确 |
| `accessDenied.invalidIp` | 403 | **来源 IP 不在 Key 白名单中** | 到开发者站点更新 Key 的 IP 白名单 |
| `privateWarLog` | 403 | 该部落的战争日志为私密 | 属正常业务状态，提示用户即可 |
| `notFound` | 404 | 标签 / ID 不存在 | 校验标签是否正确 |
| `notInWar` | 404 | 该部落当前不在部落战中 | 属正常业务状态，非错误 |
| `requestThrottled` | 429 | 超过速率限制 | 指数退避重试 + 降低并发 |
| `inMaintenance` | 503 | 服务器维护中 | 稍后重试 |
| `requestAborted` | 504 | 请求超时被中断 | 重试 |
| `unknownException` | 500 | 未知服务端错误 | 重试；持续失败可到官方 Discord 反馈 |

> **提示**：`notInWar` 与 `privateWarLog` 属于**业务状态**而非真正的故障，
> 在代码中应单独分支处理，避免污染错误监控告警。

---

## 7. 通用数据结构

### Badge（部落徽章）

```json
{
  "small":  "https://api-assets.clashofclans.com/badges/70/xxx.png",
  "medium": "https://api-assets.clashofclans.com/badges/200/xxx.png",
  "large":  "https://api-assets.clashofclans.com/badges/512/xxx.png"
}
```

### Icon（联赛图标）

```json
{
  "tiny":   "https://api-assets.clashofclans.com/leaguetiers/...",
  "small":  "https://api-assets.clashofclans.com/leaguetiers/...",
  "medium": "https://api-assets.clashofclans.com/leaguetiers/..."
}
```

> 标签（Label）的 Icon 无 `tiny`；Unranked 图标无 `medium`。

### Location（地区）

```json
{
  "id": 32000001,
  "name": "China",
  "isCountry": true,
  "countryCode": "CN",
  "localizedName": "中国"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 地区 ID（全球为 `32000000`） |
| `name` | string | 地区名称 |
| `isCountry` | bool | 是否为国家 |
| `countryCode` | string | ISO 3166-1 alpha-2 国家代码 |
| `localizedName` | string | 本地化名称（可选） |

### Label（标签）

```json
{
  "id": 56000000,
  "name": "Friendly",
  "iconUrls": { "small": "...", "medium": "..." }
}
```

### ChatLanguage（聊天语言）

```json
{ "id": 0, "name": "English", "languageCode": "EN" }
```

### Season（赛季统计）

```json
{ "id": "2024-01", "rank": 1234, "trophies": 5123 }
```

### LegendStatistics（传奇统计）

```json
{
  "legendTrophies": 1234,
  "currentSeason":  { "id": "2024-01", "rank": 100, "trophies": 5100 },
  "previousSeason": { "id": "2023-12", "rank": 200, "trophies": 5000 },
  "bestSeason":     { "id": "2023-06", "rank": 50,  "trophies": 5500 },
  "previousBuilderBaseSeason": { "id": "2024-01", "rank": 10, "trophies": 4000 },
  "bestBuilderBaseSeason":     { "id": "2023-11", "rank": 5,  "trophies": 4200 }
}
```

### PlayerHouse（玩家小屋装饰）

```json
{
  "elements": [
    { "type": "ground", "id": 93000000 },
    { "type": "walls",  "id": 93000001 }
  ]
}
```

### Paging（分页游标）

```json
{ "cursors": { "after": "xxx", "before": "yyy" } }
```

### 列表响应包装

所有列表接口统一返回：

```json
{
  "items": [ /* 资源数组 */ ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

## 8. 接口总览

| # | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 1 | GET | `/clans` | 搜索部落 |
| 2 | GET | `/clans/{clanTag}` | 获取部落详情 |
| 3 | GET | `/clans/{clanTag}/members` | 获取部落成员列表 |
| 4 | GET | `/clans/{clanTag}/warlog` | 获取部落战日志 |
| 5 | GET | `/clans/{clanTag}/currentwar` | 获取当前部落战 |
| 6 | GET | `/clans/{clanTag}/currentwar/leaguegroup` | 获取 CWL 联赛小组 |
| 7 | GET | `/clanwarleagues/wars/{warTag}` | 获取 CWL 单场战争 |
| 8 | GET | `/clans/{clanTag}/capitalraidseasons` | 获取都城突袭赛季 |
| 9 | GET | `/players/{playerTag}` | 获取玩家档案 |
| 10 | POST | `/players/{playerTag}/verifytoken` | 校验玩家 API Token |
| 11 | GET | `/leaguetiers` | 获取联赛层级列表 |
| 12 | GET | `/leaguetiers/{leagueId}` | 获取单个联赛层级 |
| 13 | GET | `/warleagues` | 获取部落对战联赛列表 |
| 14 | GET | `/warleagues/{leagueId}` | 获取单个部落对战联赛 |
| 15 | GET | `/capitalleagues` | 获取都城联赛列表 |
| 16 | GET | `/capitalleagues/{leagueId}` | 获取单个都城联赛 |
| 17 | GET | `/builderbaseleagues` | 获取建筑大师基地联赛列表 |
| 18 | GET | `/builderbaseleagues/{leagueId}` | 获取单个建筑大师基地联赛 |
| 19 | GET | `/leagues` | 获取联赛列表（赛季接口的 id 来源） |
| 20 | GET | `/leagues/{leagueId}/seasons` | 获取联赛赛季列表 |
| 21 | GET | `/leagues/{leagueId}/seasons/{seasonId}` | 获取赛季玩家排名 |
| 22 | GET | `/locations` | 获取地区列表 |
| 23 | GET | `/locations/{locationId}` | 获取单个地区 |
| 24 | GET | `/locations/{locationId}/rankings/clans` | 部落排行榜 |
| 25 | GET | `/locations/{locationId}/rankings/players` | 玩家排行榜 |
| 26 | GET | `/locations/{locationId}/rankings/clans-builder-base` | 建筑大师基地部落排行榜 |
| 27 | GET | `/locations/{locationId}/rankings/players-builder-base` | 建筑大师基地玩家排行榜 |
| 28 | GET | `/locations/{locationId}/rankings/capitals` | 都城排行榜 |
| 29 | GET | `/labels/clans` | 获取部落标签列表 |
| 30 | GET | `/labels/players` | 获取玩家标签列表 |
| 31 | GET | `/goldpass/seasons/current` | 获取当前黄金令牌赛季 |

---

## 9. 接口详情

### 9.1 部落 Clans

---

#### 9.1.1 搜索部落

```http
GET /v1/clans
```

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 否 | 部落名称关键字（支持部分匹配） |
| `warFrequency` | string | 否 | 战争频率，见[枚举值](#10-枚举值参考) |
| `locationId` | int | 否 | 地区 ID |
| `minMembers` | int | 否 | 最小成员数 |
| `maxMembers` | int | 否 | 最大成员数 |
| `minClanPoints` | int | 否 | 最低部落奖杯数 |
| `minClanLevel` | int | 否 | 最低部落等级 |
| `labelIds` | string | 否 | 标签 ID，多个以英文逗号分隔 |
| `limit` | int | 否 | 单页条数，`1`–`50`，默认 `10` |
| `after` / `before` | string | 否 | 分页游标 |

**响应示例**

```json
{
  "items": [
    {
      "tag": "#2PP",
      "name": "示例部落",
      "type": "open",
      "description": "欢迎加入",
      "location": { "id": 32000001, "name": "China", "isCountry": true, "countryCode": "CN" },
      "chatLanguage": { "id": 0, "name": "English", "languageCode": "EN" },
      "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
      "clanLevel": 15,
      "clanPoints": 45000,
      "clanBuilderBasePoints": 30000,
      "clanCapitalPoints": 1200,
      "capitalLeague": { "id": 85000000, "name": "Bronze League" },
      "requiredTrophies": 2000,
      "requiredBuilderBaseTrophies": 1000,
      "requiredTownhallLevel": 10,
      "warFrequency": "always",
      "warWinStreak": 5,
      "warWins": 320,
      "warTies": 12,
      "warLosses": 88,
      "isWarLogPublic": true,
      "warLeague": { "id": 48000000, "name": "Crystal League I" },
      "members": 48,
      "labels": [ { "id": 56000000, "name": "Friendly", "iconUrls": { "small": "...", "medium": "..." } } ],
      "isFamilyFriendly": true
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

> 搜索结果中的部落对象**不含** `memberList` 与 `clanCapital` 字段。

---

#### 9.1.2 获取部落详情

```http
GET /v1/clans/{clanTag}
```

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `clanTag` | 部落标签（URL 编码），如 `%232PP` |

**查询参数**：无

**响应示例**

```json
{
  "tag": "#2PP",
  "name": "示例部落",
  "type": "inviteOnly",
  "description": "部落描述文本",
  "location": { "id": 32000001, "name": "China", "isCountry": true, "countryCode": "CN" },
  "chatLanguage": { "id": 0, "name": "English", "languageCode": "EN" },
  "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
  "clanLevel": 15,
  "clanPoints": 45000,
  "clanBuilderBasePoints": 30000,
  "clanCapitalPoints": 1200,
  "capitalLeague": { "id": 85000000, "name": "Bronze League" },
  "requiredTrophies": 2000,
  "requiredBuilderBaseTrophies": 1000,
  "requiredTownhallLevel": 10,
  "warFrequency": "always",
  "warWinStreak": 5,
  "warWins": 320,
  "warTies": 12,
  "warLosses": 88,
  "isWarLogPublic": true,
  "warLeague": { "id": 48000000, "name": "Crystal League I" },
  "members": 48,
  "memberList": [
    {
      "tag": "#9QJ8L0",
      "name": "玩家昵称",
      "role": "leader",
      "expLevel": 200,
      "townHallLevel": 15,
      "leagueTier": { "id": 105000036, "name": "Legend I", "iconUrls": { "small": "...", "medium": "..." } },
      "builderBaseLeague": { "id": 44000000, "name": "..." },
      "trophies": 5200,
      "builderBaseTrophies": 3000,
      "clanRank": 1,
      "previousClanRank": 1,
      "donations": 1500,
      "donationsReceived": 200,
      "playerHouse": { "elements": [ { "type": "ground", "id": 93000000 } ] }
    }
  ],
  "labels": [ { "id": 56000000, "name": "Friendly", "iconUrls": { "small": "...", "medium": "..." } } ],
  "clanCapital": {
    "capitalHallLevel": 10,
    "districts": [
      { "id": 70000000, "name": "Capital Peak", "districtHallLevel": 10 },
      { "id": 70000001, "name": "Barbarian Camp", "districtHallLevel": 5 }
    ]
  },
  "isFamilyFriendly": true
}
```

**`clanLevel` / 成员对象字段说明**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `role` | string | `member` / `admin` / `coLeader` / `leader` |
| `leagueTier` | object | 玩家所在联赛层级（含 `iconUrls`） |
| `builderBaseLeague` | object | 建筑大师基地联赛（**无** `iconUrls`） |
| `clanRank` | int | 当前部落内排名 |
| `previousClanRank` | int | 上次统计时部落内排名 |
| `donations` | int | 本周捐兵数 |
| `donationsReceived` | int | 本周收兵数 |

---

#### 9.1.3 获取部落成员列表

```http
GET /v1/clans/{clanTag}/members
```

**查询参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | int | `50` | 单页条数，`1`–`50` |
| `after` / `before` | string | — | 分页游标 |

**响应示例**

```json
{
  "items": [
    {
      "tag": "#9QJ8L0",
      "name": "玩家昵称",
      "role": "coLeader",
      "expLevel": 180,
      "townHallLevel": 14,
      "leagueTier": { "id": 105000025, "name": "Titan League 25", "iconUrls": { "small": "...", "medium": "..." } },
      "builderBaseLeague": { "id": 44000000, "name": "..." },
      "trophies": 4800,
      "builderBaseTrophies": 2800,
      "clanRank": 3,
      "previousClanRank": 2,
      "donations": 900,
      "donationsReceived": 300
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

#### 9.1.4 获取部落战日志

```http
GET /v1/clans/{clanTag}/warlog
```

**查询参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | int | `50` | 单页条数，`1`–`50` |
| `after` / `before` | string | — | 分页游标 |

**响应示例**

```json
{
  "items": [
    {
      "result": "win",
      "endTime": "2024-01-15T08:30:00.000Z",
      "battleModifier": "none",
      "teamSize": 15,
      "attacksPerMember": 2,
      "clan": {
        "tag": "#2PP",
        "name": "示例部落",
        "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
        "clanLevel": 15,
        "attacks": 28,
        "stars": 42,
        "destructionPercentage": 87.5,
        "expEarned": 240
      },
      "opponent": {
        "tag": "#8QQ",
        "name": "对手部落",
        "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
        "clanLevel": 14,
        "attacks": 30,
        "stars": 38,
        "destructionPercentage": 80.2,
        "expEarned": 180
      }
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

> `result` 取值：`win` / `lose` / `tie`，若为 `null` 表示战争尚未结束。
> 若部落战争日志为私密，返回 `403 privateWarLog`。

---

#### 9.1.5 获取当前部落战

```http
GET /v1/clans/{clanTag}/currentwar
```

**查询参数**：无

**响应示例（战斗中）**

```json
{
  "state": "inWar",
  "teamSize": 15,
  "attacksPerMember": 2,
  "battleModifier": "none",
  "preparationStartTime": "2024-01-14T08:00:00.000Z",
  "startTime": "2024-01-14T08:00:00.000Z",
  "endTime": "2024-01-15T08:00:00.000Z",
  "clan": {
    "tag": "#2PP",
    "name": "示例部落",
    "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
    "clanLevel": 15,
    "attacks": 20,
    "stars": 30,
    "destructionPercentage": 62.3,
    "members": [
      {
        "tag": "#9QJ8L0",
        "name": "玩家昵称",
        "mapPosition": 1,
        "townhallLevel": 15,
        "opponentAttacks": 2,
        "bestOpponentAttack": {
          "order": 5,
          "attackerTag": "#8QQ01",
          "defenderTag": "#9QJ8L0",
          "stars": 2,
          "destructionPercentage": 78,
          "duration": 165
        },
        "attacks": [
          {
            "order": 3,
            "attackerTag": "#9QJ8L0",
            "defenderTag": "#8QQ05",
            "stars": 3,
            "destructionPercentage": 100,
            "duration": 172
          }
        ]
      }
    ]
  },
  "opponent": {
    "tag": "#8QQ",
    "name": "对手部落",
    "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
    "clanLevel": 14,
    "attacks": 18,
    "stars": 26,
    "destructionPercentage": 55.1,
    "members": []
  }
}
```

**状态说明**

| `state` | 含义 |
| --- | --- |
| `notInWar` | 未处于部落战中 |
| `preparation` | 备战日 |
| `inWar` | 战斗日 |
| `warEnded` | 战争已结束 |

> ⚠️ 该接口**存在缓存**。战斗期间数据通常有 1–2 分钟延迟；
> 若需更实时的数据，可附加查询参数 `?realtime=true`（部分社区库采用此做法，官方文档未明确列出）。

---

#### 9.1.6 获取 CWL 联赛小组

```http
GET /v1/clans/{clanTag}/currentwar/leaguegroup
```

**查询参数**：无

**响应示例**

```json
{
  "state": "inWar",
  "season": "2024-01",
  "clans": [
    {
      "tag": "#2PP",
      "name": "示例部落",
      "clanLevel": 15,
      "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
      "members": [
        { "tag": "#9QJ8L0", "name": "玩家昵称", "townHallLevel": 15 }
      ]
    }
  ],
  "rounds": [
    { "warTags": ["#ABC123", "#DEF456", "#0"] },
    { "warTags": ["#GHI789", "#0", "#0"] }
  ]
}
```

**说明**

- `state` 取值：`notInWar` / `preparation` / `inWar` / `ended`
- `rounds` 数组每一项代表一轮，`warTags` 中每个标签对应一场战争
- **`#0` 表示该轮次尚未匹配或已轮空**，遇到时应跳过
- 拿到 `warTags` 后需逐个调用 [9.2.2](#922-获取-cwl-单场战争) 获取战争详情

---

#### 9.1.7 获取都城突袭赛季

```http
GET /v1/clans/{clanTag}/capitalraidseasons
```

**查询参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | int | `10` | 单页条数，`1`–`50` |
| `after` / `before` | string | — | 分页游标 |

**响应示例**

```json
{
  "items": [
    {
      "state": "ended",
      "startTime": "2024-01-05T07:00:00.000Z",
      "endTime": "2024-01-08T07:00:00.000Z",
      "capitalTotalLoot": 1250000,
      "raidsCompleted": 6,
      "totalAttacks": 152,
      "enemyDistrictsDestroyed": 42,
      "offensiveReward": 810,
      "defensiveReward": 125,
      "members": [
        {
          "tag": "#9QJ8L0",
          "name": "玩家昵称",
          "attacks": 6,
          "attackLimit": 5,
          "bonusAttackLimit": 1,
          "capitalResourcesLooted": 45000
        }
      ],
      "attackLog": [
        {
          "defender": {
            "tag": "#8QQ",
            "name": "对手部落",
            "level": 14,
            "badgeUrls": { "small": "...", "medium": "...", "large": "..." }
          },
          "attackCount": 12,
          "districtCount": 6,
          "districtsDestroyed": 4,
          "districts": [
            {
              "id": 70000000,
              "name": "Capital Peak",
              "districtHallLevel": 10,
              "destructionPercent": 100,
              "attackCount": 3,
              "totalLooted": 25000
            }
          ]
        }
      ],
      "defenseLog": [
        {
          "attacker": {
            "tag": "#7RR",
            "name": "进攻方部落",
            "level": 16,
            "badgeUrls": { "small": "...", "medium": "...", "large": "..." }
          },
          "attackCount": 10,
          "districtCount": 6,
          "districtsDestroyed": 5,
          "districts": []
        }
      ]
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

> `state` 取值：`ongoing`（进行中）/ `ended`（已结束）

---

### 9.2 部落战与联赛战 Clan Wars

#### 9.2.1 获取 CWL 联赛小组

见 [9.1.6](#916-获取-cwl-联赛小组)。

---

#### 9.2.2 获取 CWL 单场战争

```http
GET /v1/clanwarleagues/wars/{warTag}
```

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `warTag` | 战争标签（URL 编码），来自 leaguegroup 的 `rounds[].warTags` |

**查询参数**：无

**响应结构**：与 [9.1.5 当前部落战](#915-获取当前部落战) 完全一致。

> ⚠️ CWL 战争中 **`attacksPerMember` 字段不存在**（常规部落战才有）。
> 判断方式：字段缺失即为 CWL。

---

### 9.3 玩家 Players

---

#### 9.3.1 获取玩家档案

```http
GET /v1/players/{playerTag}
```

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `playerTag` | 玩家标签（URL 编码），如 `%239QJ8L0` |

**查询参数**：无

**响应示例**

```json
{
  "tag": "#9QJ8L0",
  "name": "玩家昵称",
  "townHallLevel": 15,
  "townHallWeaponLevel": 5,
  "expLevel": 200,
  "trophies": 5200,
  "bestTrophies": 5500,
  "warStars": 3200,
  "attackWins": 1500,
  "defenseWins": 320,
  "builderHallLevel": 10,
  "builderBaseTrophies": 3000,
  "bestBuilderBaseTrophies": 3200,
  "donations": 1500,
  "donationsReceived": 200,
  "clanCapitalContributions": 250000,
  "role": "leader",
  "warPreference": "in",
  "clan": {
    "tag": "#2PP",
    "name": "示例部落",
    "clanLevel": 15,
    "badgeUrls": { "small": "...", "medium": "...", "large": "..." }
  },
  "leagueTier": {
    "id": 105000036,
    "name": "Legend I",
    "iconUrls": { "small": "...", "large": "..." }
  },
  "builderBaseLeague": { "id": 44000000, "name": "..." },
  "legendStatistics": {
    "legendTrophies": 1234,
    "currentSeason":  { "id": "2024-01", "rank": 100, "trophies": 5100 },
    "previousSeason": { "id": "2023-12", "rank": 200, "trophies": 5000 },
    "bestSeason":     { "id": "2023-06", "rank": 50,  "trophies": 5500 }
  },
  "achievements": [
    {
      "name": "Keep Your Account Safe!",
      "stars": 3,
      "value": 1,
      "target": 1,
      "info": "Protect your account...",
      "completionInfo": "Completed!",
      "village": "home"
    }
  ],
  "troops": [
    { "name": "Barbarian", "level": 12, "maxLevel": 12, "village": "home" }
  ],
  "heroes": [
    { "name": "Barbarian King", "level": 95, "maxLevel": 95, "village": "home",
      "equipment": [ { "name": "Barbarian Puppet", "level": 18, "maxLevel": 18, "village": "home" } ] }
  ],
  "spells": [
    { "name": "Lightning Spell", "level": 11, "maxLevel": 11, "village": "home" }
  ],
  "heroEquipment": [
    { "name": "Giant Gauntlet", "level": 18, "maxLevel": 18, "village": "home" }
  ],
  "labels": [ { "id": 57000000, "name": "Clan Wars", "iconUrls": { "small": "...", "medium": "..." } } ],
  "playerHouse": { "elements": [ { "type": "ground", "id": 93000000 } ] }
}
```

**字段说明**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `role` | string | 部落中的职位，无部落时字段缺失 |
| `warPreference` | string | `in`（参战）/ `out`（不参战） |
| `leagueTier` | object | 联赛层级（含 `iconUrls`） |
| `builderBaseLeague` | object | 建筑大师基地联赛（**无** `iconUrls`） |
| `achievements[].village` | string | `home` / `builderBase` |
| `troops[].superTroopIsActive` | bool | 该兵种是否有超级兵种形态处于激活状态 |
| `heroes[].equipment` | array | 该英雄佩戴的装备（结构同 `troops`） |

---

#### 9.3.2 校验玩家 API Token

```http
POST /v1/players/{playerTag}/verifytoken
```

用于校验玩家在游戏内 **设置 → 更多设置 → API Token** 中生成的令牌，
常用于「验证玩家是否真正拥有该账号」的场景。

**请求头**

```http
Authorization: Bearer <你的_API_Token>
Content-Type: application/json
```

**请求体**

```json
{ "token": "玩家游戏内生成的令牌" }
```

**响应示例（校验通过）**

```json
{
  "tag": "#9QJ8L0",
  "token": "玩家提供的令牌",
  "status": "ok"
}
```

**响应示例（校验失败）**

```json
{
  "tag": "#9QJ8L0",
  "token": "玩家提供的令牌",
  "status": "invalid"
}
```

> `status` 取值：`ok` / `invalid`

---

### 9.4 联赛 Leagues

#### 9.4.1 获取联赛层级列表

> **不要和 `/leagues` 混用**：本接口返回的是**联赛层级 tier**，id 为 `105000xxx`
> （`105000034` Legend III / `105000035` Legend II / `105000036` Legend I）；
> 而 `/leagues` 返回的是另一套 id `290000xx`（Legend League = `29000022`）。
> 赛季接口只认后者（见 9.4.9）。

```http
GET /v1/leaguetiers
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    {
      "id": 105000036,
      "name": "Legend I",
      "iconUrls": { "small": "...", "large": "..." }
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

#### 9.4.2 获取单个联赛层级

```http
GET /v1/leaguetiers/{leagueId}
```

**响应**

```json
{
  "id": 105000036,
  "name": "Legend I",
  "iconUrls": { "small": "...", "large": "..." }
}
```

---

#### 9.4.3 获取部落对战联赛列表

```http
GET /v1/warleagues
```

```json
{
  "items": [ { "id": 48000000, "name": "Crystal League I" } ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

#### 9.4.4 获取单个部落对战联赛

```http
GET /v1/warleagues/{leagueId}
```

```json
{ "id": 48000000, "name": "Crystal League I" }
```

---

#### 9.4.5 获取都城联赛列表

```http
GET /v1/capitalleagues
```

```json
{
  "items": [ { "id": 85000000, "name": "Bronze League" } ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

#### 9.4.6 获取单个都城联赛

```http
GET /v1/capitalleagues/{leagueId}
```

```json
{ "id": 85000000, "name": "Bronze League" }
```

---

#### 9.4.7 获取建筑大师基地联赛列表

```http
GET /v1/builderbaseleagues
```

```json
{
  "items": [ { "id": 44000000, "name": "..." } ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

#### 9.4.8 获取单个建筑大师基地联赛

```http
GET /v1/builderbaseleagues/{leagueId}
```

```json
{ "id": 44000000, "name": "..." }
```

---

#### 9.4.9 获取联赛赛季列表

```http
GET /v1/leagues/{leagueId}/seasons
```

> **`leagueId` 必须来自 `/leagues`（`290000xx`），而且只有 Legend League（`29000022`）有赛季。**
> 实测（2026-10-21）：
>
> - `/warleagues` 的 `48000000` → `400 Unknown value for parameter leagueId`
> - `/leaguetiers` 的 `105000036` → 同样 `400 Unknown value for parameter leagueId`
> - `/leagues` 的 `29000020` / `29000021` → `400 Seasons are available only for legendary league`
> - `/leagues` 的 `29000022` → `200`
>
> 返回的 `items` **由旧到新**（从 `2015-07` 开始）分页给出，拿当前赛季必须顺着
> `paging.cursors.after` 翻到最后一页，不能取 `items[0]`。赛季元素只有 `id`，
> 没有 `name` / `startTime`。

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [ { "id": "2015-07" }, { "id": "2015-08" } ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

#### 9.4.10 获取赛季玩家排名

```http
GET /v1/leagues/{leagueId}/seasons/{seasonId}
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    {
      "tag": "#9QJ8L0",
      "name": "玩家昵称",
      "expLevel": 200,
      "trophies": 5200,
      "attackWins": 1500,
      "defenseWins": 320,
      "rank": 1,
      "previousRank": 3,
      "clan": {
        "tag": "#2PP",
        "name": "示例部落",
        "badgeUrls": { "small": "...", "medium": "...", "large": "..." }
      }
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

### 9.5 地区与排行榜 Locations

#### 9.5.1 获取地区列表

```http
GET /v1/locations
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    { "id": 32000000, "name": "Global", "isCountry": false },
    { "id": 32000001, "name": "China", "isCountry": true, "countryCode": "CN" }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

> 全球（Global）的地区 ID 固定为 **`32000000`**。

---

#### 9.5.2 获取单个地区

```http
GET /v1/locations/{locationId}
```

```json
{ "id": 32000001, "name": "China", "isCountry": true, "countryCode": "CN" }
```

---

#### 9.5.3 部落排行榜

```http
GET /v1/locations/{locationId}/rankings/clans
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    {
      "tag": "#2PP",
      "name": "示例部落",
      "location": { "id": 32000001, "name": "China", "isCountry": true, "countryCode": "CN" },
      "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
      "clanLevel": 15,
      "clanPoints": 45000,
      "members": 48,
      "rank": 1,
      "previousRank": 2
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

#### 9.5.4 玩家排行榜

```http
GET /v1/locations/{locationId}/rankings/players
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    {
      "tag": "#9QJ8L0",
      "name": "玩家昵称",
      "expLevel": 200,
      "trophies": 5200,
      "attackWins": 1500,
      "defenseWins": 320,
      "rank": 1,
      "previousRank": 3,
      "clan": { "tag": "#2PP", "name": "示例部落", "badgeUrls": { "small": "...", "medium": "...", "large": "..." } },
      "leagueTier": { "id": 105000036, "name": "Legend I", "iconUrls": { "small": "...", "large": "..." } }
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

#### 9.5.5 建筑大师基地部落排行榜

```http
GET /v1/locations/{locationId}/rankings/clans-builder-base
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    {
      "tag": "#2PP",
      "name": "示例部落",
      "location": { "id": 32000001, "name": "China", "isCountry": true, "countryCode": "CN" },
      "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
      "clanLevel": 15,
      "clanBuilderBasePoints": 30000,
      "members": 48,
      "rank": 1,
      "previousRank": 2
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

#### 9.5.6 建筑大师基地玩家排行榜

```http
GET /v1/locations/{locationId}/rankings/players-builder-base
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    {
      "tag": "#9QJ8L0",
      "name": "玩家昵称",
      "expLevel": 200,
      "builderBaseTrophies": 3000,
      "rank": 1,
      "previousRank": 2,
      "clan": { "tag": "#2PP", "name": "示例部落", "clanLevel": 15, "badgeUrls": { "small": "...", "medium": "...", "large": "..." } },
      "builderBaseLeague": { "id": 44000000, "name": "..." }
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

#### 9.5.7 都城排行榜

```http
GET /v1/locations/{locationId}/rankings/capitals
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    {
      "tag": "#2PP",
      "name": "示例部落",
      "location": { "id": 32000001, "name": "China", "isCountry": true, "countryCode": "CN" },
      "badgeUrls": { "small": "...", "medium": "...", "large": "..." },
      "clanLevel": 15,
      "clanCapitalPoints": 1200,
      "members": 48,
      "rank": 1,
      "previousRank": 1
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

### 9.6 标签 Labels

#### 9.6.1 获取部落标签列表

```http
GET /v1/labels/clans
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

```json
{
  "items": [
    {
      "id": 56000000,
      "name": "Friendly",
      "iconUrls": { "small": "https://api-assets.clashofclans.com/labels/...", "medium": "..." }
    }
  ],
  "paging": { "cursors": { "after": "...", "before": "..." } }
}
```

---

#### 9.6.2 获取玩家标签列表

```http
GET /v1/labels/players
```

**查询参数**：`limit`（默认 `10`，`1`–`50`）、`after`、`before`

响应结构同 [9.6.1](#961-获取部落标签列表)。

---

### 9.7 黄金令牌 Gold Pass

#### 9.7.1 获取当前黄金令牌赛季

```http
GET /v1/goldpass/seasons/current
```

**查询参数**：无

```json
{
  "startTime": "2024-01-01T07:00:00.000Z",
  "endTime": "2024-02-01T07:00:00.000Z"
}
```

---

## 10. 枚举值参考

### 部落类型 `type`

| 值 | 含义 |
| --- | --- |
| `open` | 任何人可加入 |
| `inviteOnly` | 需申请 / 邀请 |
| `closed` | 已关闭 |

### 部落职位 `role`

| 值 | 含义 |
| --- | --- |
| `member` | 成员 |
| `admin` | 长老 |
| `coLeader` | 副首领 |
| `leader` | 首领 |

### 战争频率 `warFrequency`

| 值 | 含义 |
| --- | --- |
| `always` | 始终 |
| `moreThanOncePerWeek` | 每周多次 |
| `oncePerWeek` | 每周一次 |
| `lessThanOncePerWeek` | 每周少于一次 |
| `never` | 从不 |
| `unknown` | 未知 |

### 战争状态 `state`（部落战）

| 值 | 含义 |
| --- | --- |
| `notInWar` | 未参战 |
| `preparation` | 备战日 |
| `inWar` | 战斗日 |
| `warEnded` | 已结束 |

### 联赛小组状态 `state`（CWL）

| 值 | 含义 |
| --- | --- |
| `notInWar` | 未参战 |
| `preparation` | 准备中 |
| `inWar` | 进行中 |
| `ended` | 已结束 |

### 战争结果 `result`

| 值 | 含义 |
| --- | --- |
| `win` | 胜 |
| `lose` | 负 |
| `tie` | 平 |
| `null` | 尚未结束 |

### 都城突袭状态 `state`

| 值 | 含义 |
| --- | --- |
| `ongoing` | 进行中 |
| `ended` | 已结束 |

### 参战偏好 `warPreference`

| 值 | 含义 |
| --- | --- |
| `in` | 参战 |
| `out` | 不参战 |

### 战斗模式 `battleModifier`

| 值 | 含义 |
| --- | --- |
| `none` | 普通模式 |
| `hardMode` | 困难模式 |

### 村庄类型 `village`

| 值 | 含义 |
| --- | --- |
| `home` | 家乡 |
| `builderBase` | 建筑大师基地 |

### 玩家小屋元素 `playerHouse.elements[].type`

| 值 | 含义 |
| --- | --- |
| `ground` | 地面 |
| `walls` | 城墙 |
| `roof` | 屋顶 |
| `decoration` | 装饰 |
| `foot` | 底座 |

### Token 校验状态 `status`

| 值 | 含义 |
| --- | --- |
| `ok` | 校验通过 |
| `invalid` | 校验失败 |

### 常见 ID 区间

> 以下为社区实践中观察到的 ID 分布，用于快速判断 ID 类型，
> **非官方文档保证**，请勿在业务逻辑中硬编码依赖。
> 其中「全球」地区 ID `32000000` 是稳定且广泛使用的固定值。

| 资源 | ID 区间 |
| --- | --- |
| 地区 - 全球 | `32000000` |
| 地区 - 国家 / 区域 | `32000001` 起 |
| 联赛（`/leagues`，赛季 id 来源） | `29000000` 起；Legend League = `29000022` |
| 联赛层级（`/leaguetiers`） | `105000000` 起；Legend I/II/III = `105000034`–`105000036` |
| 建筑大师基地联赛 | `44000000` 起 |
| 部落对战联赛 War League | `48000000` 起 |
| 部落 / 玩家标签 | `56000000` 起 |
| 玩家标签 | `57000000` 起 |
| 都城地区 District | `70000000` 起 |
| 都城联赛 Capital League | `85000000` 起 |
| 玩家小屋元素 | `93000000` 起 |

---

## 11. 调用示例

### 11.1 cURL

```bash
# 获取部落详情
curl -s -H "Authorization: Bearer $COC_API_TOKEN" \
     "https://api.clashofclans.com/v1/clans/%232PP"

# 搜索部落（分页）
curl -s -H "Authorization: Bearer $COC_API_TOKEN" \
     "https://api.clashofclans.com/v1/clans?name=clash&limit=10"

# 获取当前部落战
curl -s -H "Authorization: Bearer $COC_API_TOKEN" \
     "https://api.clashofclans.com/v1/clans/%232PP/currentwar"

# 校验玩家 Token
curl -s -X POST \
     -H "Authorization: Bearer $COC_API_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"token":"玩家游戏内令牌"}' \
     "https://api.clashofclans.com/v1/players/%239QJ8L0/verifytoken"
```

### 11.2 Python（requests）

```python
import requests
from urllib.parse import quote

API_TOKEN = "eyJ0eXAiOiJKV1Qi..."          # 建议从环境变量读取
BASE_URL = "https://api.clashofclans.com/v1"

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})


def get_clan(clan_tag: str) -> dict:
    """获取部落详情。clan_tag 形如 '#2PP'"""
    tag = quote(clan_tag)                   # '#' -> '%23'
    resp = session.get(f"{BASE_URL}/clans/{tag}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def search_clans(name: str, limit: int = 10) -> dict:
    resp = session.get(
        f"{BASE_URL}/clans",
        params={"name": name, "limit": limit},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_current_war(clan_tag: str) -> dict:
    tag = quote(clan_tag)
    resp = session.get(f"{BASE_URL}/clans/{tag}/currentwar", timeout=10)
    if resp.status_code == 404 and resp.json().get("reason") == "notInWar":
        return {"state": "notInWar"}
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    print(get_clan("#2PP")["name"])
```

### 11.3 Python（带限流与重试的完整封装）

```python
import time
import logging
import requests
from urllib.parse import quote

log = logging.getLogger(__name__)

BASE_URL = "https://api.clashofclans.com/v1"


class CocApiError(Exception):
    """API 返回的业务错误。"""

    def __init__(self, status: int, reason: str, message: str):
        self.status = status
        self.reason = reason
        self.message = message
        super().__init__(f"[{status}] {reason}: {message}")


class CocClient:
    """
    Clash of Clans API 客户端。

    - 令牌桶限流，默认 10 req/s
    - 429 / 5xx 指数退避重试
    - 业务状态（notInWar / privateWarLog）作为异常抛出，便于分支处理
    """

    def __init__(self, token: str, rate_limit: float = 10.0):
        self._min_interval = 1.0 / rate_limit
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def request(self, path: str, *, method: str = "GET", retries: int = 4, **kwargs):
        url = f"{BASE_URL}{path}"
        for attempt in range(retries):
            self._throttle()
            resp = self._session.request(method, url, timeout=15, **kwargs)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (429, 500, 503, 504):
                wait = 2 ** attempt
                log.warning("限流/服务异常 %s，%s 秒后重试", resp.status_code, wait)
                time.sleep(wait)
                continue

            # 400 / 403 / 404：不重试
            body = resp.json() if resp.content else {}
            raise CocApiError(
                resp.status_code,
                body.get("reason", "unknown"),
                body.get("message", ""),
            )

        raise CocApiError(resp.status_code, "retryExhausted", "重试次数已用尽")

    # ---- 业务方法 ----

    def get_clan(self, clan_tag: str) -> dict:
        return self.request(f"/clans/{quote(clan_tag)}")

    def get_clan_members(self, clan_tag: str, limit: int = 50, after: str | None = None) -> dict:
        params = {"limit": limit}
        if after:
            params["after"] = after
        return self.request(f"/clans/{quote(clan_tag)}/members", params=params)

    def get_current_war(self, clan_tag: str) -> dict:
        return self.request(f"/clans/{quote(clan_tag)}/currentwar")

    def get_player(self, player_tag: str) -> dict:
        return self.request(f"/players/{quote(player_tag)}")

    def verify_player_token(self, player_tag: str, token: str) -> dict:
        return self.request(
            f"/players/{quote(player_tag)}/verifytoken",
            method="POST",
            json={"token": token},
        )
```

### 11.4 分页遍历示例

```python
def iter_clan_members(client, clan_tag: str):
    """自动翻页遍历全部部落成员。"""
    after = None
    while True:
        data = client.get_clan_members(clan_tag, limit=50, after=after)
        yield from data["items"]

        cursors = (data.get("paging") or {}).get("cursors") or {}
        after = cursors.get("after")
        if not after:
            break
```

### 11.5 Node.js（fetch）

```javascript
const TOKEN = process.env.COC_API_TOKEN;
const BASE_URL = 'https://api.clashofclans.com/v1';

async function cocGet(path) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  const body = await res.json();
  if (!res.ok) {
    const err = new Error(`[${res.status}] ${body.reason}: ${body.message}`);
    err.status = res.status;
    err.reason = body.reason;
    throw err;
  }
  return body;
}

// 使用
const clan = await cocGet(`/clans/${encodeURIComponent('#2PP')}`);
console.log(clan.name);
```

---

## 12. 附录：社区库中的非公开接口

以下接口出现在维护良好的社区库（如 `clashofclans.js`）中，但**未收录于官方 Swagger 文档**。
它们可能依赖特定权限或处于灰度阶段，**使用前请自行验证可用性**，不要作为核心依赖。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/players/{playerTag}/battlelog` | 玩家战斗日志 |
| GET | `/players/{playerTag}/leaguehistory` | 玩家联赛历史 |
| GET | `/leaguegroup/{leagueGroupTag}/{seasonId}` | 联赛小组详情 |

参考响应结构：

```jsonc
// /players/{playerTag}/battlelog
{
  "items": [{
    "battleType": "legend",              // legend | homeVillage | ranked
    "attack": true,
    "armyShareCode": "...",
    "opponentPlayerTag": "#8QQ01",
    "stars": 3,
    "destructionPercentage": 100,
    "lootedResources":       [{ "name": "Gold", "amount": 500000 }],
    "extraLootedResources":  [],
    "availableLoot":         [{ "name": "Gold", "amount": 800000 }]
  }]
}

// /players/{playerTag}/leaguehistory
{
  "items": [{
    "leagueSeasonId": 202401,
    "leagueTrophies": 5200,
    "leagueTierId": 105000036,
    "placement": 1,
    "attackWins": 8, "attackLosses": 2, "attackStars": 22,
    "defenseWins": 5, "defenseLosses": 3, "defenseStars": 14,
    "maxBattles": 10
  }]
}
```

---

## 附：本文档的数据来源与校验说明

| 来源 | 用途 |
| --- | --- |
| `https://developer.clashofclans.com/` 前端 Bundle | 获取官方「Getting Started」原文（鉴权、IP 绑定、限流、响应格式说明） |
| `mathsman5133/coc.py`（Python 客户端） | 交叉验证接口路径与响应字段名 |
| `clashperk/clashofclans.js`（TypeScript 客户端） | 交叉验证接口路径、完整响应类型定义、错误码表 |

> 官方文档页面（`/#/documentation`）通过 **Swagger UI** 渲染，
> 其 OpenAPI 规范地址由登录后的接口动态下发（`swaggerUrl`），
> 因此**无法匿名获取**该规范文件；本文档的接口清单与字段定义
> 均来自上述三个来源的交叉验证。
>
> 由于游戏持续更新，字段可能随版本增减，建议以实际调用结果为准。

---

## 附：常见问题（FAQ）

**Q1：返回 `403 accessDenied.invalidIp` 怎么办？**
A：你的服务器公网出口 IP 不在 Key 的白名单中。登录 <https://developer.clashofclans.com/>，
编辑对应 Key 的 IP Addresses 字段，加入当前 IP。

**Q2：返回 `403 accessDenied` 但没写 invalidIp？**
A：`Authorization` 头缺失或格式错误。正确格式为 `Bearer <token>`（注意中间有一个空格）。

**Q3：小程序 / 前端能直接调用吗？**
A：不能。API 要求固定 IP 白名单，且 Token 一旦下发到客户端就会泄露。
必须通过自己的后端中转。

**Q4：`currentwar` 数据有延迟？**
A：该接口有服务端缓存，战斗期间通常有 1–2 分钟延迟，属正常现象。
需要更细粒度的实时性时，应提高轮询频率并配合本地缓存。

**Q5：`notInWar` 是错误吗？**
A：不是。它表示该部落当前没有进行中的部落战，属于正常业务状态，
代码中应与真正的错误分开处理。

**Q6：如何获取 CWL 某一场具体战争？**
A：先调用 `/clans/{tag}/currentwar/leaguegroup` 拿到 `rounds[].warTags`，
再对每个非 `#0` 的标签调用 `/clanwarleagues/wars/{warTag}`。

**Q7：Key 失效了怎么办？**
A：Token 是 JWT，官方未公开其确切有效期策略。若确认 IP 白名单无误、
Header 格式正确，但请求仍持续返回 `403 accessDenied`，标准做法是
到开发者站点**删除旧 Key 并重新创建**，然后更新服务端配置。
建议把 Token 放在环境变量或配置中心，便于随时轮换。
