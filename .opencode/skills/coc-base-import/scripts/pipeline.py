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
    """把 ``duration`` 秒等分成 ``count`` 段，返回每段靠前 20% 的时间点。

    视频里每个阵型停留时长基本一致（本片约 3s/个），没有转场检测也够用；
    取段首 20% 是为了避开换阵瞬间的过场动画。``--mapping`` 用来兜底修正。
    """
    if count <= 0:
        return []
    interval = duration / count
    return [i * interval + interval * 0.2 for i in range(count)]


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


def download_video(video_url: str, workdir: Path) -> Path:
    """下载 720p 以内的单文件版本（不合并，避免依赖 PATH 上的 ffmpeg）。"""
    workdir.mkdir(parents=True, exist_ok=True)
    existing = sorted(workdir.glob("video.*"))
    if existing:
        return existing[0]

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        "b[height<=720][ext=mp4]/b[height<=720]",
        "--no-playlist",
        "-o",
        str(workdir / "video.%(ext)s"),
        video_url,
    ]
    subprocess.run(cmd, check=True)
    videos = sorted(workdir.glob("video.*"))
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
                "3",
                str(out),
            ],
            check=True,
            capture_output=True,
        )
        frames.append(out)
    return frames


def load_links(args: argparse.Namespace, bvid: str) -> dict[int, str]:
    """链接来源：``--links`` 优先，否则抓置顶评论再解析。"""
    if args.links:
        raw = json.loads(Path(args.links).read_text(encoding="utf-8"))
        return {
            int(number): bili_links.normalize_layout_link(str(code))
            for number, code in raw.items()
        }

    texts = bili_links.fetch_pinned(bvid, Path(args.cookies))
    links: dict[int, str] = {}
    for text in texts:
        links.update(bili_links.parse_layout_codes(text))
    return links


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
        "--cookies",
        default=".secrets/bilibili-cookies.txt",
        help="B 站 cookie（Netscape 格式），默认 .secrets/bilibili-cookies.txt",
    )
    parser.add_argument("--links", help="手工链接 JSON：{编号: 分享码或完整 URL}")
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

    links = load_links(args, bvid)
    if not links:
        print("没有解析到任何阵型链接：置顶笔记可能是图片，或 cookie 失效。", file=sys.stderr)
        print("按 references/workflow.md 手工建 links.json，再用 --links 传入。", file=sys.stderr)
        return 1

    mapping = load_mapping(args.mapping)
    video = download_video(args.video_url, workdir)
    duration = video_duration(video)
    frames = extract_frames(video, frame_timestamps(duration, args.count), workdir / "frames")

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
                    "source_site": "bilibili",
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
