# 阵型导入的细节与排障

## cookie 怎么来

1. 浏览器登录 B 站，打开任意视频页。
2. 用扩展导出 cookie 为 **Netscape 格式**（常见扩展：Get cookies.txt LOCALLY /
   EditThisCookie）。至少要有 `SESSDATA` 与 `bili_jct`。
3. 存成仓库根目录的 `.secrets/bilibili-cookies.txt`（已 gitignore，绝不入库）。
4. 验证：`python -c "import http.cookiejar; j=http.cookiejar.MozillaCookieJar('.secrets/bilibili-cookies.txt'); j.load(ignore_discard=True, ignore_expires=True); print(len(j))"`
   —— 条数为 0 说明格式不对或文件不存在。

cookie 过期后表现是评论接口返回 `-101` / `-352`；重新导出即可。

## 置顶笔记是图片 / 解析不到链接

脚本按「文本」解析 `#1 / 1号 + TH18:XX:xxxx`，并会自动跟进置顶评论里的
`bilibili.com/opus/...` 笔记正文。仍然解析不到编号时，它会**退出码非 0**，
并把抓到的原文（含笔记 JSON、图片 URL）写到 `{workdir}/links.raw.txt`
（默认 `.cache/coc-base-import/links.raw.txt`）。

这时按原文手工建 `links.json`：

```json
{
  "1": "TH18:WB:AAAARAAAAAAphHQWN6eIhzQedsGoEvXp",
  "2": "https://link.clashofclans.com/?action=OpenLayout&id=TH18%3AHV%3A..."
}
```

- 键是**视频画面上的编号**（1 起）。
- 值可以是分享码（脚本自动补官方 URL 并做 URL 编码），也可以是完整链接。
- 命令里加 `--links links.json`，此时不再抓评论（可以先离线工作）。

## 编号对不上：`--mapping`

抽帧是按「总时长 ÷ 数量」等分的，若视频中间有片头/片尾或某个阵型多停了几秒，
第 N 帧可能对应画面上的另一个编号。先跑 `--dry-run` 看表格，再建：

```json
{ "1": 3, "2": 1 }
```

含义：**第 1 个抽帧 → 用链接编号 3；第 2 个抽帧 → 用链接编号 1**。标题里的
`#N` 始终用抽帧序号（也就是画面上的角标），只有取链接的编号被替换。

## 缓存与目录

```
.cache/coc-base-import/
└── BV1qHpY62EoT/          # 每个视频一个目录（换视频不会命中上一个的缓存）
    ├── video.mp4
    └── frames/01.jpg …
```

- 想重新下载同一个视频：删掉该 BV 目录再跑。
- `links.raw.txt` 写在 `{workdir}` 根下，不是 BV 目录里。

## 常见错误码

| 现象 | 含义 | 处置 |
| --- | --- | --- |
| 401 | 管理员账号/口令错，或服务器未设置 `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 检查环境变量；两者任一为空时后端一律 401 |
| 403 | 站点/反向代理拒绝 | 检查站点是否要求额外鉴权、IP 是否被拦 |
| 413 | 单张图片超过 5 MiB | 抽帧已是 JPEG q=3，正常不会；检查是否拿错文件 |
| 400 `INVALID_PARAMS` | 标题为空、URL 非法、图片不是 JPEG/PNG/WebP | 看响应 `error.message` |
| 200 + `duplicated=true` | 内容哈希命中，已存在 | 正常，不算失败 |

## 重复怎么判定

后端对 `标题 + 大本等级 + 链接 + 来源 URL + 图片字节` 做 sha256（`content_hash`）。
字段完全相同才会判重；改了标题就会新增一条。**重跑前不要改标题模板**，
否则 30 条会变 60 条。
