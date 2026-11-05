"""阵型视频导入流水线（命令行入口）。

一条命令：下载视频 → 按节拍抽帧 → 解析置顶笔记里的阵型链接 → 逐条调用
``POST /api/v1/admin/bases`` 入库。任何一步的失败都会在结尾汇总，并以非 0
退出码结束，方便 CI 或人工重跑时发现。

用法示例见 ``SKILL.md``；``python pipeline.py --help`` 是参数的唯一权威。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import bili_links
from upload import UploadError, upload_one


def frame_timestamps(duration: float, count: int) -> list[float]:
    """把 ``duration`` 秒等分成 ``count`` 段，返回每段**正中间**的时间点。

    视频里每个阵型停留时长基本一致（本片约 3.04s/个），没有转场检测也够用。
    **必须取段中**：取段首时正好压在「阵型切换 + 编号角标未定格」的那一瞬间，
    实测会拍到上一个阵型（或角标被切掉一半），整条数据错位一格。``--mapping``
    仍可用来兜底修正。
    """
    if count <= 0:
        return []
    interval = duration / count
    return [i * interval + interval * 0.5 for i in range(count)]


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def video_duration(video: Path) -> float:
    """用 ffmpeg 读时长。ffmpeg 只检查文件时返回码是 1，忽略即可。"""
    proc = subprocess.run(
        [_ffmpeg(), "-i", str(video)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", proc.stderr)
    if not match:
        raise RuntimeError(f"读不出视频时长：{video}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def video_cache_dir(workdir: Path, bvid: str) -> Path:
    """每个视频独占一个缓存目录：``{workdir}/{BV号}/``。

    **不能共用一个 ``workdir/video.*``**：换了 ``--video-url`` 重跑时会命中
    上一个视频的缓存，抽出来的是别人的画面，而链接按新视频解析 —— 两边编号
    对不上却不会报错。
    """
    return Path(workdir) / bvid


def download_video(video_url: str, workdir: Path, bvid: str | None = None) -> Path:
    """下载 1080P 以内的**视频轨**（不合并音轨，抽帧不需要声音）。

    **尽量取 1080P**：480P 的抽帧在页面上放大后阵型细节糊成一片（用户实拍反馈）。
    B 站匿名只缺「1080P 高码率」（大会员），普通 1080P 轨匿名可取。
    """
    bvid = bvid or bili_links.extract_bvid(video_url)
    target = video_cache_dir(workdir, bvid)
    target.mkdir(parents=True, exist_ok=True)

    existing = sorted(target.glob("video.*"))
    if existing:
        return existing[0]

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        # B 站匿名只能拿到 DASH 的**纯视频轨**（没有 `b` 这种音视频合一的格式），
        # 所以必须用 `bv*`。1080P 匿名可取（只有「1080P 高码率」要大会员），
        # 而 480P 放大后阵型细看不清 —— 从高往低退。
        "bv*[height<=1080][ext=mp4]/bv*[height<=720][ext=mp4]/bv*[height<=480][ext=mp4]/bv*",
        "--no-playlist",
        "-o",
        str(target / "video.%(ext)s"),
        video_url,
    ]
    subprocess.run(cmd, check=True)
    videos = sorted(target.glob("video.*"))
    if not videos:
        raise RuntimeError("yt-dlp 没有产出视频文件")
    return videos[0]


def extract_frames(video: Path, timestamps: list[float], frames_dir: Path) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()
    frames: list[Path] = []
    for index, ts in enumerate(timestamps, start=1):
        out = frames_dir / f"{index:02d}.jpg"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                # q=2 在 1080P 下约 600 KiB/张（30 张约 18 MiB），仍远低于 5 MiB 上限；
                # 比 q=3 明显耐放大，阵型页点开看细节不糊。
                "2",
                str(out),
            ],
            check=True,
            capture_output=True,
        )
        frames.append(out)
    return frames


def _article_cache_path(workdir: str | Path, cvid: str) -> Path:
    return Path(workdir) / "links.cache" / f"cv{cvid}.json"


def load_article(cvid: str, cookies: str, workdir: str | Path | None) -> dict[str, object]:
    """抓专栏正文，**成功过就落盘复用**。

    B 站对 ``x/article/view`` 的匿名请求限流很紧（``-352`` / ``-509`` 一轮接一轮），
    抓一次就缓存能省掉大量重试；同一条命令重跑（幂等验证）也不再打上游。
    """
    cache = _article_cache_path(workdir, cvid) if workdir else None
    if cache is not None and cache.is_file():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            payload = {}
        content = (payload.get("data") or {}).get("content")
        if content:
            return {
                "texts": [bili_links.html_to_text(str(content))],
                "raw": payload,
            }

    article = bili_links.fetch_article(cvid, cookies)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(article["raw"], ensure_ascii=False), encoding="utf-8")
    return article


def load_links(
    links_path: str | None,
    cookies: str,
    bvid: str,
    comments_file: str | None = None,
    workdir: str | Path | None = None,
) -> tuple[dict[int, str], str, bool]:
    """解析 ``编号 → 链接``。

    返回 ``(links, raw_text, from_file)``：

    - ``links_path`` 给了 ``--links`` 就直接用（``from_file=True``，人工清单可信）；
    - ``comments_file`` 给了 ``--comments-file`` 就当作置顶评论正文（无需 cookie）；
    - 否则抓置顶评论；置顶被折叠成专栏（``note_cvid``）或 ``bilibili.com/opus/...``
      笔记时**跟进抓正文**（失败只记录，不中断）；
    - ``raw_text`` 是拿到的全部原始文本（+ 笔记 JSON），解析失败时由调用方落盘，
      供人工看图/手工补 ``links.json``。
    """
    if links_path:
        raw = json.loads(Path(links_path).read_text(encoding="utf-8"))
        return (
            {
                int(number): bili_links.normalize_layout_link(str(code))
                for number, code in raw.items()
            },
            "",
            True,
        )

    if comments_file:
        texts = [Path(comments_file).read_text(encoding="utf-8")]
        raw_parts = list(texts)
        links: dict[int, str] = {}
        for text in texts:
            links.update(bili_links.parse_layout_codes(text))
        return links, "\n\n---\n\n".join(raw_parts), False

    payload = bili_links.fetch_pinned_payload(bvid, Path(cookies))
    texts = bili_links.extract_pinned_texts(payload)
    raw_parts = list(texts)
    links: dict[int, str] = {}
    for text in texts:
        links.update(bili_links.parse_layout_codes(text))

    # 置顶正文被折叠成「笔记」(note_cvid)：真正的链接在专栏里。
    #
    # **无条件跟进**：折叠预览里可能残留「1:」这种半截条目，不能因为
    # 「已经解析出东西」就跳过专栏。专栏是权威文本，覆盖预览里的任何值。
    # 跟进失败不算致命 —— 把错误记进原文，主流程再按「没有/缺号」处理。
    for cvid in bili_links.extract_pinned_cvids(payload):
        try:
            article = load_article(cvid, cookies, workdir)
        except RuntimeError as exc:
            raw_parts.append(f"[取专栏 cv{cvid} 失败] {exc}")
            continue
        raw_parts.append(json.dumps(article["raw"], ensure_ascii=False, indent=2))
        for text in article["texts"]:
            links.update(bili_links.parse_layout_codes(text))

    # 置顶只贴了 opus 动态链接：跟进抓正文。
    for opus_id in bili_links.extract_opus_ids(texts):
        try:
            note = bili_links.fetch_opus(opus_id, Path(cookies))
        except RuntimeError as exc:
            raw_parts.append(f"[取笔记 {opus_id} 失败] {exc}")
            continue
        raw_parts.append(json.dumps(note["raw"], ensure_ascii=False, indent=2))
        for text in note["texts"]:
            links.update(bili_links.parse_layout_codes(text))

    return links, "\n\n---\n\n".join(raw_parts), False


def missing_numbers(links: dict[int, str], count: int, mapping: dict[int, int]) -> list[int]:
    """抽帧需要的链接编号里，哪些没解析到。"""
    required = {mapping.get(index, index) for index in range(1, count + 1)}
    return sorted(required - set(links))


def write_raw(workdir: Path, raw_text: str) -> Path:
    """把抓到的原始文本落盘，方便人工看图补 ``links.json``。"""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "links.raw.txt"
    target.write_text(raw_text or "（没有抓到任何文本）", encoding="utf-8")
    return target


def load_mapping(path: str | None) -> dict[int, int]:
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(video_no): int(link_no) for video_no, link_no in raw.items()}


def build_rows(
    th_level: int,
    links: dict[int, str],
    mapping: dict[int, int],
    frames: list[Path],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, frame in enumerate(frames, start=1):
        source_number = mapping.get(index, index)
        rows.append(
            {
                "index": index,
                "time": None,
                "link": links.get(source_number),
                "source_number": source_number,
                "title": f"#{index} {th_level}本传奇防守阵",
                "image": frame,
            }
        )
    return rows


def print_table(rows: list[dict[str, object]]) -> None:
    print(f"{'#':>3}  {'链接编号':>4}  {'链接':<64} 图片")
    for row in rows:
        link = row["link"] or "（缺链接）"
        print(
            f"{row['index']:>3}  {row['source_number']:>6}  {link:<64} "
            f"{Path(str(row['image'])).name}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把 B 站阵型分享视频里的阵型（截图 + 置顶笔记链接）批量上传到站点。",
    )
    parser.add_argument("--video-url", required=True, help="B 站视频 URL")
    parser.add_argument("--count", type=int, default=30, help="视频里的阵型数量（默认 30）")
    parser.add_argument("--th-level", type=int, default=18, help="大本等级（默认 18）")
    parser.add_argument(
        "--source-site", default="bilibili", help="来源站点名（默认 bilibili）"
    )
    parser.add_argument(
        "--cookies",
        default=".secrets/bilibili-cookies.txt",
        help="B 站 cookie（Netscape 格式），默认 .secrets/bilibili-cookies.txt",
    )
    parser.add_argument("--links", help="手工链接 JSON：{编号: 分享码或完整 URL}")
    parser.add_argument(
        "--comments-file",
        help="把置顶评论/笔记正文存成本地文本文件，直接解析（不需要 cookie）",
    )
    parser.add_argument(
        "--mapping",
        help="抽帧编号 → 链接编号的修正 JSON，如 {\"1\": 3, \"2\": 1}",
    )
    parser.add_argument(
        "--workdir",
        default=".cache/coc-base-import",
        help="下载与抽帧的临时目录（默认 .cache/coc-base-import）",
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="站点根地址（默认 http://127.0.0.1:8000）",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("COC_ADMIN_USER", ""),
        help="管理员账号（默认读 COC_ADMIN_USER）",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("COC_ADMIN_PASSWORD", ""),
        help="管理员口令（默认读 COC_ADMIN_PASSWORD）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只下载/抽帧/打印映射，不上传")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bvid = bili_links.extract_bvid(args.video_url)
    workdir = Path(args.workdir)

    links, raw_text, from_file = load_links(
        args.links, args.cookies, bvid, args.comments_file, workdir
    )
    if not links:
        print("没有解析到任何阵型链接：置顶笔记可能是图片，或 cookie 失效。", file=sys.stderr)
        if not from_file:
            print(f"原始文本已存到 {write_raw(workdir, raw_text)}", file=sys.stderr)
        print("按 references/workflow.md 手工建 links.json，再用 --links 传入。", file=sys.stderr)
        return 1

    mapping = load_mapping(args.mapping)
    gaps = missing_numbers(links, args.count, mapping)
    if gaps and not from_file:
        # 缺号的链接一上传就是半套数据，且事后很难补 —— 先停下来让人核对。
        print(f"缺少编号：{gaps}", file=sys.stderr)
        print(f"原始文本已存到 {write_raw(workdir, raw_text)}", file=sys.stderr)
        print("补一份 links.json 后用 --links 传入（见 references/workflow.md）。", file=sys.stderr)
        return 1
    if gaps:
        print(f"提醒：links.json 里没有编号 {gaps}，对应抽帧会被跳过。", file=sys.stderr)
    video = download_video(args.video_url, workdir, bvid)
    duration = video_duration(video)
    frames = extract_frames(
        video, frame_timestamps(duration, args.count), video.parent / "frames"
    )

    rows = build_rows(args.th_level, links, mapping, frames)
    for row, ts in zip(rows, frame_timestamps(duration, args.count), strict=True):
        row["time"] = round(ts, 2)
    print_table(rows)

    if args.dry_run:
        return 0

    if not args.user or not args.password:
        print("缺少管理员凭据：请设 COC_ADMIN_USER / COC_ADMIN_PASSWORD。", file=sys.stderr)
        return 1

    created = duplicated = missing = 0
    failures: list[str] = []
    for row in rows:
        if not row["link"]:
            missing += 1
            print(f"跳过 #{row['index']}：缺链接", file=sys.stderr)
            continue
        try:
            data = upload_one(
                Path(str(row["image"])),
                {
                    "title": row["title"],
                    "th_level": args.th_level,
                    "layout_link": row["link"],
                    "source_url": args.video_url,
                    "source_site": args.source_site,
                },
                args.api_base,
                args.user,
                args.password,
            )
        except UploadError as exc:
            failures.append(f"#{row['index']}: HTTP {exc.status} {exc.message}")
            continue
        if data.get("duplicated"):
            duplicated += 1
        else:
            created += 1

    print(f"\n完成：新增 {created}，重复 {duplicated}，缺链接 {missing}，失败 {len(failures)}")
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    return 0 if not failures and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
