---
name: COC 阵型导入
description: 把 B 站阵型分享视频里的阵型（截图 + 置顶笔记链接）批量上传到 COCPersonal 站点。Use when the user gives a bilibili video link and asks to import/upload its base layouts.
---

# COC 阵型导入

一条命令完成：下载视频 → 按固定节拍抽帧 → 解析置顶评论里的阵型分享码 →
逐条调用站点的管理员上传接口。**全部脚本在 `scripts/`，不依赖站点代码。**

## 1. 前置检查

```bash
python -c "import yt_dlp, imageio_ffmpeg, requests" || pip install yt-dlp imageio-ffmpeg requests
test -f .secrets/bilibili-cookies.txt || echo "缺 cookie，见 references/workflow.md"
curl -sf "$COC_API_BASE/readyz" > /dev/null && echo "站点就绪"
```

- `.secrets/bilibili-cookies.txt`：浏览器导出的 **Netscape 格式** cookie。
  匿名抓评论会 403 / `-352`，必须带登录态。
- 服务器凭据走环境变量 `COC_ADMIN_USER` / `COC_ADMIN_PASSWORD`，
  **不要写进命令历史或文件**。
- 站点根地址 `COC_API_BASE`（例如 `https://coc.example.com`）。

## 2. 先 dry-run，让人确认映射

```bash
python .opencode/skills/coc-base-import/scripts/pipeline.py \
  --video-url "https://www.bilibili.com/video/BV1qHpY62EoT/" \
  --count 30 --th-level 18 --dry-run
```

打印「视频编号 / 链接编号 / 链接 / 图片」。**逐行核对**：

- 链接编号与画面上 `#N` 角标是否一一对应；对不上时用 `--mapping`（见
  `references/workflow.md`）。
- 置顶评论若是 `bilibili.com/opus/...` 笔记链接，脚本会自动跟进抓正文（图片笔记
  抓不到文字）。
- **解析失败或缺号会直接退出（非 0）**，并把抓到的原始文本存成
  `{workdir}/links.raw.txt`。此时按 workflow 手工建 `links.json`，
  加 `--links links.json` 重跑 dry-run —— 脚本不会带着半套链接上传。

把这张表给用户看过、确认无误后再进入下一步。

## 3. 正式上传

同一条命令去掉 `--dry-run`，补上凭据与站点地址：

```bash
COC_ADMIN_USER=... COC_ADMIN_PASSWORD=... \
python .opencode/skills/coc-base-import/scripts/pipeline.py \
  --video-url "https://www.bilibili.com/video/BV1qHpY62EoT/" \
  --count 30 --th-level 18 \
  --api-base "$COC_API_BASE"
```

- 重复内容后端返回 200 + `duplicated=true`，脚本计入「重复」，不报错。
- 上传即发布（无审核队列）。

## 4. 核对

```bash
curl -s "$COC_API_BASE/api/v1/bases?page_size=50" | python -c \
  "import json,sys; d=json.load(sys.stdin)['data']; print(d['total'], len(d['items']))"
```

应看到总数 = 阵型数量，且 `items` 的 `imagePath` 以 `/media/bases/` 开头。
再跑一次同样的导入命令：应当全部是「重复」，总数不增加（幂等）。

## 5. 汇报

向用户报告：新增 / 重复 / 缺链接 / 失败 各自的数量；缺号与失败的**具体编号**
和原因（401 = 凭据错、403 = 站点拒绝、413 = 图片超 5 MiB）。不要只说「完成了」。
