# 阵型功能与视频导入流水线设计

- 日期：2026-11-04
- 状态：待人工评审
- 路径：`docs/superpowers/specs/2026-11-04-coc-base-layouts-design.md`
- 取代：`2026-10-23-warreport-data-design.md` §3.2「不做阵型内容（页面占位，接口与数据表都不动）」
- 范围：`/bases` 页转正、管理员上传接口、B 站视频 → 阵型入库的脚本与项目 skill

## 1. 背景与目标

`/bases` 目前是占位页，`base_layouts` 表、投稿表、后台视图早已存在但从未对外可用。
本次把它做成真正能用的阵型库，并把「一条 B 站阵型分享视频 → 30 条阵型上站」固化成可重跑的流程。

目标：

1. `/bases` 能浏览阵型：图片、大本等级、复制阵型链接、来源标注。
2. 站长能在页面上传「阵型链接 + 阵型图片」，**上传即发布**。
3. 把指定视频（`BV1qHpY62EoT`，30 个 18 本阵型）的截图与链接批量入库。
4. 上述批量过程提炼为项目内 skill，下次给新链接直接重跑。

成功标准：

- `/bases` 打开能看到 30 条 18 本阵型；点图能看大图，点「复制链接」拿到可用的
  `link.clashofclans.com` 链接。
- 上传表单能独立新增一条阵型，刷新后仍在。
- 重复跑同一批导入不会产生重复记录（幂等）。
- 换一个新视频链接，skill 能完成「下载 → 抽帧 → 解析链接 → 上传 → 报告」。

## 2. 已核实的现状

| 东西 | 状态 |
| --- | --- |
| `base_layouts` 表 | 已有：`title/title_zh/description/th_level/layout_link/image_path/source_url/source_site/content_hash/copy_count/is_published/submission_id/created_at` |
| 投稿接口 `POST /api/v1/submissions` | 已有，无鉴权，写入 `pending`；本次不复用 |
| 后台 `BaseLayoutView` | 已有，只读 |
| `/media/` 静态目录 | `deploy/nginx.conf` 已有，`alias /data/media/`、`autoindex off`、`expires 7d` |
| `media` 卷 | compose 已声明，api 读写、web 只读；`MEDIA_ROOT=/data/media` |
| `GET /api/v1/bases` | **缺** |
| 图片上传端点 | **缺**（`MEDIA_ROOT` 配置项至今无人使用） |
| 前端 `/bases` | 占位页 |
| 数据库迁移 | **本次不需要**，现有列足够 |

推论：这是一次「补上缺席的三块」的改动，不需要新表、不需要改部署拓扑。

## 3. 关键决策

| 决策 | 取值 | 理由 |
| --- | --- | --- |
| 上传入口面向谁 | **仅站长，上传即发布** | 批量导入是站长自己的活；公开投稿会引入审核与滥用防护，本期不做 |
| 鉴权方式 | HTTP Basic，凭据复用 `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 已有单一管理员账号，不新造 token 表；后台改密码后上传口同步生效 |
| 图片存储 | 服务端本地 `media` 卷，URL 前缀 `/media/` | 基建已备好；不引入对象存储与额外依赖 |
| 阵型分类 | 只按 `th_level` 筛选，不做标签 | 视频没有标签信息；先上内容，标签等有真实需求再加 |
| 幂等键 | `content_hash = sha256(规范化字段 + 图片字节 hash)` | 重跑导入不产生重复；投稿表已有同名字段的先例 |
| 视频编号识别 | **按节拍切帧，不 OCR** | Ekwaak 的片子固定每个阵型停留约 3 秒、编号 `#1`–`#30` 顺序递增；OCR 反而更脆 |
| 图片形态 | 保留整帧（含 `#N` 角标与来源字幕），转 JPEG | 角标本身就是编号证据，来源字幕就是署名；不裁切可避免切掉陷阱 |
| 置顶笔记获取 | 用户提供 `cookies.txt` | 匿名访问 B 站评论接口返回 403/-352，`yt-dlp` 匿名只能拿到普通评论 |

## 4. 后端

### 4.1 公开只读接口

`GET /api/v1/bases`

- 查询参数：`th_level?: int`、`page=1`、`page_size=20`
- 分页复用 `clamp_page_size`（上限 50，**截断不报错**）
- 只返回 `is_published = true`
- 排序：`created_at DESC, id DESC`
- 响应：

```json
{
  "data": {
    "items": [
      {
        "id": 1,
        "title": "#1 18本传奇防守阵",
        "thLevel": 18,
        "layoutLink": "https://link.clashofclans.com/?action=OpenLayout&id=...",
        "imagePath": "/media/bases/2026/11/<uuid>.jpg",
        "sourceUrl": "https://www.bilibili.com/video/BV1qHpY62EoT/",
        "sourceSite": "bilibili",
        "createdAt": "2026-11-04T12:00:00Z"
      }
    ],
    "total": 30
  },
  "meta": { "cache": "HIT", "fetched_at": null, "age_seconds": null, "ttl_seconds": 0 }
}
```

本期**不做**详情接口：页面用弹窗看大图，不引入详情路由。

### 4.2 管理员上传接口

`POST /api/v1/admin/bases`，`multipart/form-data`

鉴权：

- 读 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 环境变量，`secrets.compare_digest` 比对
- **任一为空时一律 401**（避免空环境变量导致空凭据通过）
- 未通过返回 `401`，带 `WWW-Authenticate: Basic realm="coc-admin"`，错误体走统一格式 `{"error": {"code": "UNAUTHORIZED", ...}}`

字段：

| 字段 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| `title` | text | 是 | 去空白后非空，≤ 100 字 |
| `th_level` | int | 否 | 1–100 |
| `layout_link` | text | 否 | ≤ 2048，只允许 `http://` / `https://`；建议 `link.clashofclans.com` |
| `image` | file | 否 | ≤ 5 MiB；JPEG / PNG / WebP |
| `source_url` | text | 否 | ≤ 2048，`http(s)` |
| `source_site` | text | 否 | ≤ 50，默认 `bilibili` |

- `layout_link` 与 `image` **至少一个**，否则 400 `INVALID_PARAMS`
- 图片校验：**忽略客户端声明的 `Content-Type`**，读取前 12 字节按 magic bytes 判定
  （JPEG `FFD8FF`、PNG `89504E47`、WebP `RIFF....WEBP`）；都不匹配一律 400
  —— 扩展名与 Content-Type 都不可信
- 读取时最多读 `5 MiB + 1` 字节，超出返回 `413 PAYLOAD_TOO_LARGE`
- 落盘：`{MEDIA_ROOT}/bases/YYYY/MM/{uuid4}.{jpg|png|webp}`，目录按需创建
- 入库：`image_path` 存相对 URL `/media/bases/YYYY/MM/<uuid>.<ext>`，
  `is_published = true`，`source_site` 默认 `bilibili`，`created_at = now(UTC)`
- 幂等：`content_hash = sha256("v1|" + title + "|" + th_level + "|" + layout_link + "|" + source_url + "|" + sha256(图片字节))`
  - 已存在同 hash 的记录：返回 `200`，`data` 为已存在记录，并附 `"duplicated": true`
  - 不存在：返回 `201`，`"duplicated": false`
  - 重复命中时**不重复写文件**
- 响应形状与公开接口单条一致，额外带 `duplicated`
- 实现落点：`backend/app/api/routes/bases.py`（公开列表 + 管理员上传），
  在 `app/main.py` 注册；图片校验与落盘抽成模块内纯函数，便于单测

### 4.3 静态文件

- 生产：nginx 的 `/media/` 已经指向该卷，无需改动
- 本地：`create_app()` 只在 `MEDIA_ROOT` **已存在**时挂载 `StaticFiles` 到 `/media`
  （默认值 `/data/media` 在 Windows 上不存在，不能为了挂载去凭空造目录）
- 上传时按需创建 `{MEDIA_ROOT}/bases/YYYY/MM/`
- 前端 Vite 增加 `/media` → `http://127.0.0.1:8000` 代理（与 `/api` 并列）
- 本地联调前设置 `MEDIA_ROOT` 到一个真实目录（如 `backend/.media`，加进 `.gitignore`）

### 4.4 配置

- `Settings.media_root` 已存在，不改
- 上传大小上限写成模块常量 `MAX_IMAGE_BYTES = 5 * 1024 * 1024`，不做成环境变量（YAGNI）

### 4.5 测试

`backend/tests/api/test_bases_api.py`：

1. 列表只出 `is_published`
2. `th_level=18` 过滤生效，其它等级不出现
3. `page_size=500` 截断为 50 且返回 200
4. 上传：无 `Authorization` → 401；密码错 → 401；环境变量为空 → 401
5. 上传 PNG：201、`is_published=true`、文件落在 `MEDIA_ROOT` 下、`imagePath` 以 `/media/` 开头
6. 名为 `.png` 的文本文件（magic bytes 不是任何图片）→ 400
7. 超过 5 MiB → 413
8. 既无链接又无图片 → 400
9. 同内容重复上传 → 第二次 200 且 `duplicated=true`，记录数仍为 1
10. 未发布记录不出现在列表里（造一条 `is_published=false` 的假数据）

## 5. 前端

### 5.1 阵型页 `/bases`

- 顶部：标题 + 等级筛选（`全部 / 16 / 17 / 18`）+ 右上「上传阵型」按钮
- 卡片网格（响应式，2–4 列）：
  - 封面图（`/media/...`，懒加载），点击 `el-image` 大图预览
  - 标题、`TH18` 徽标
  - 「复制链接」按钮：`navigator.clipboard.writeText`，失败回落 `window.open`；
    成功提示「已复制阵型链接」。**没有 `layoutLink` 的条目不渲染按钮**，
    改为一行小字「国服需照图手摆」
  - 来源行：「来源：Ekwaak / Big Legends」（有 `sourceUrl` 时为新窗口链接）
- 分页：首屏请求 `page_size=24`；`total` 大于已加载数时底部显示「加载更多」，
  追加下一页；切换等级筛选时重置回第一页
- 空态：「暂无阵型」；加载中用 `LoadingBlock`；失败用 `ErrorCard` + 重试
- 底部沿用 `SourceNote`（版权/署名约束见 `docs/deployment.md` §12）

### 5.2 上传弹窗

- 入口：页头「上传阵型」按钮
- 字段：标题、大本等级（默认 18）、阵型链接、图片（`el-upload`，单文件）、来源 URL
- 口令：弹窗内输入管理员账号/密码，成功一次后存 `sessionStorage`，
  刷新页面即失效；前端**不内置任何默认账号密码**
- 提交：`multipart/form-data` + `Authorization: Basic ...`
- 成功后关闭弹窗、刷新列表、提示「已上传」；401 提示「账号或密码不对」；
  其余错误展示后端 message

### 5.3 代码落点

- `frontend/src/api/endpoints.ts`：`getBases`、`getBase`、`uploadBase` 与类型
  `BaseLayoutItem`、`BasesPage`、`UploadBaseInput`（**所有 URL 只出现在这里**）
- `frontend/src/api/request.ts`：`RequestOptions` 增加 `headers`，让 `uploadBase`
  能带 Basic 头；不改现有错误归一化逻辑
- `frontend/src/pages/Bases.vue`：页面本体
- `frontend/src/pages/Bases.spec.ts`：重写占位测试
- `frontend/vite.config.ts`：加 `/media` 代理

### 5.4 前端测试

1. 列表渲染条数与标题、`TH18` 徽标
2. 等级筛选切换会带 `th_level=18` 重新请求
3. 复制按钮调用剪贴板并提示
4. 上传表单：缺标题/缺链接与图片时给校验提示，不发起请求
5. 401 时提示账号密码错误

## 6. 导入流水线与项目 skill

### 6.1 目录

```text
.opencode/skills/coc-base-import/
├── SKILL.md
├── scripts/
│   ├── pipeline.py        # 下载 → 抽帧 → 解析链接 → 上传，一条命令
│   ├── bili_links.py      # wbi 签名 + 置顶评论/笔记解析
│   └── upload.py          # 管理员接口客户端（可独立重试）
└── references/
    └── workflow.md        # 失败处置、cookie 导出、人工映射兜底
```

- 脚本只依赖 `yt-dlp`、`imageio-ffmpeg`（自带 ffmpeg 二进制）、`requests`；
  用后端同一套 Python 环境安装：`python -m pip install yt-dlp imageio-ffmpeg requests`
- cookie 路径固定 `.secrets/bilibili-cookies.txt`，`.secrets/` 与 `backend/.media/` 加入 `.gitignore`

### 6.2 流程

1. **下载**：`yt-dlp -f "bv*[height<=720]"` 下到临时目录
2. **抽帧**：`ffprobe` 取时长 `D`，按 `N = --count`（默认 30）计算 `interval = D / N`，
   在第 `i` 帧的 `i*interval + 0.2*interval` 处取图；输出 `01.jpg`–`30.jpg`（JPEG q=3）
3. **解析链接**：
   - 用 cookie 调 `x/v2/reply/wbi/main`（脚本内实现 wbi 签名）
   - 优先取置顶评论；评论里若是 `bilibili.com/opus/...` 笔记链接，再抓笔记正文
   - 按 `1号: TH18:WB:...` / `#19：TH18:HV:...` 解析出 `编号 → 链接`
   - 简写码补全为 `https://link.clashofclans.com/?action=OpenLayout&id=<urlencode(code)>`
   - 解析失败或缺号：写 `links.raw.txt` 并以非零码退出，提示用 `--links links.json` 手工补
4. **上传**：逐条 multipart 调 `POST /api/v1/admin/bases`；
   `COC_API_BASE`（默认本机 8000）、`COC_ADMIN_USER`、`COC_ADMIN_PASSWORD`
5. **报告**：成功/重复/失败三组；失败带 HTTP 状态与后端 message；任一失败则退出码非零

### 6.3 命令行

```powershell
python .opencode/skills/coc-base-import/scripts/pipeline.py `
  --video-url "https://www.bilibili.com/video/BV1qHpY62EoT/" `
  --count 30 --th-level 18 --source-site bilibili `
  --api-base http://127.0.0.1:8000
```

- `--dry-run`：只下载、抽帧、解析链接，打印「编号 → 标题 → 链接 → 图片」表格，不上传
- `--links links.json`：跳过评论解析，用人工清单
- `--mapping map.json`：覆盖编号顺序（节拍失准时用）

### 6.4 SKILL.md

- frontmatter：`name: COC 阵型导入`；`description` 覆盖中文触发语
  「把这个 B 站视频里的阵型上传到站点 / 批量导入阵型」
- 触发语：给一个 B 站阵型视频链接，要求把里面的阵型上传到站点
- 前置检查：cookie 存在且未过期、`COC_ADMIN_*` 已设置、目标站点 `/readyz` 正常
- 执行：先 `--dry-run` 给人看映射表，确认后再正式上传
- 收尾：访问 `GET /api/v1/bases?page_size=50` 核对条数，报告缺号与失败项

## 7. 本次要导入的内容

- 视频：`BV1qHpY62EoT`，91 秒，30 个 18 本阵型，来源 Big Legends / Ekwaak
- 标题：`#1 18本传奇防守阵` … `#30 18本传奇防守阵`
- 来源：`source_url` 指向该视频，`source_site=bilibili`
- 页面来源标注：`Ekwaak / Big Legends（付费订阅阵型，国际服）`
- 链接仅国际服可用；国服玩家只能照图手摆——页面文案要写清楚

## 8. 非目标

- 不做公开投稿、审核队列、点赞/收藏/热度
- 不做标签体系、搜索、详情独立路由
- 不做图片裁切、去水印、OCR 编号
- 不做服务端定时抓取 B 站（保持本地脚本 + skill）
- 不新增数据库迁移；不改 `deploy/nginx.conf` 与 compose

## 9. 风险与对策

| 风险 | 对策 |
| --- | --- |
| B 站 cookie 过期 / 风控 | 解析失败立即停并提示重导 cookie；`--links` 人工清单兜底 |
| 置顶「笔记」是图片而非文字 | 脚本保存原始笔记内容与图片，提示人工补 `links.json`；不硬编码解析 |
| 视频节拍不是 3 秒 | `interval` 由时长/数量推导；`--mapping` 覆盖 |
| 付费阵型转载争议 | 页面与 skill 都保留 UP 与 Big Legends 署名、原视频链接，并注明「付费订阅阵型，仅供学习」；如被要求下架，删记录即可 |
| 上传接口被爆破 | Basic 鉴权 + 现有全站限流（默认 60 次/分/IP）；口令不落前端代码 |
| Basic 口令明文传输 | 生产站点走 HTTPS 后风险可接受（`docs/deployment.md` §1 已有开关）；不上 HTTPS 时不要在公共网络使用上传功能 |
| 并发重复上传 | 查询 + 插入之间没有唯一约束，两个并发请求可能各插一条；本期只有单个管理员操作，接受该限制，不为此加约束 |
| 图片体积 | 单张 ≤ 5 MiB，抽帧统一转 JPEG；30 张约 6–10 MB |

## 10. 验收清单

1. `cd backend && python -m pytest -q` 全绿（含新增 10 个用例）
2. `cd frontend && npm run test` 全绿（含重写的 Bases 测试）
3. `cd frontend && npm run build` 通过
4. 本地：上传 1 条 → `/bases` 立即出现 → 刷新仍在 → 图片可打开
5. 本地：对同一内容再传一次 → 提示重复，列表不增加
6. 服务器：跑 skill 上传 30 条 → `/bases?page_size=50` 返回 30 条
7. 服务器：`/bases` 页面图片全部可加载，复制出的链接形如
   `https://link.clashofclans.com/?action=OpenLayout&id=TH18%3A...`
8. 再跑一次 skill → 30 条全部标记为重复，数据库仍为 30 条
