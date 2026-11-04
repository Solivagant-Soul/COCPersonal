from pathlib import Path

import pipeline
from bili_links import extract_pinned_texts, normalize_layout_link, parse_layout_codes
from pipeline import frame_timestamps

CODE = "TH18:WB:AAAARAAAAAAphHQWN6eIhzQedsGoEvXp"
BASE = "https://link.clashofclans.com/?action=OpenLayout&id="


def test_parse_numbered_codes():
    text = f"1号：{CODE}\n#19：\n\nTH18:HV:AAAAMgAAAAAptjlCMeGcYAmSmerJtLYd"
    links = parse_layout_codes(text)
    assert links[1] == BASE + "TH18%3AWB%3AAAAARAAAAAAphHQWN6eIhzQedsGoEvXp"
    assert links[19] == BASE + "TH18%3AHV%3AAAAAMgAAAAAptjlCMeGcYAmSmerJtLYd"


def test_parse_ignores_plain_code_without_number():
    assert parse_layout_codes(f"好用\n{CODE}\n") == {}


def test_parse_keeps_full_url():
    full = BASE + "TH18%3AWB%3Aabc"
    assert normalize_layout_link(full) == full


def test_later_duplicate_number_wins():
    text = "3号：TH18:WB:AAA\n3号：TH18:WB:BBB"
    assert parse_layout_codes(text)[3] == BASE + "TH18%3AWB%3ABBB"


def test_frame_timestamps_spans_duration():
    ts = frame_timestamps(91.27, 30)
    assert len(ts) == 30
    assert 0.5 < ts[0] < 0.7
    assert 88.0 < ts[-1] < 90.0


def test_extract_pinned_texts_reads_top_replies():
    payload = {
        "data": {
            "top_replies": [{"content": {"message": "笔记"}}],
            "replies": [{"content": {"message": "普通"}}],
        }
    }
    assert extract_pinned_texts(payload) == ["笔记"]


def test_download_video_ignores_other_videos_cache(tmp_path, monkeypatch):
    """换个视频重跑时不能复用上一个视频的缓存文件。"""
    # 旧版布局（共用一个 video.*）与别的视频的缓存目录都不该被采纳。
    (tmp_path / "video.mp4").write_bytes(b"legacy")
    other = tmp_path / "BV0000000000"
    other.mkdir()
    (other / "video.mp4").write_bytes(b"other")

    def fake_run(cmd, check):
        assert check is True
        out = Path(cmd[cmd.index("-o") + 1].replace("%(ext)s", "mp4"))
        out.write_bytes(b"new")

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    video = pipeline.download_video(
        "https://www.bilibili.com/video/BV1qHpY62EoT/", tmp_path
    )
    assert video.read_bytes() == b"new"
    assert video.parent == tmp_path / "BV1qHpY62EoT"


def test_download_video_reuses_same_video_cache(tmp_path, monkeypatch):
    target = tmp_path / "BV1qHpY62EoT"
    target.mkdir()
    (target / "video.mp4").write_bytes(b"cached")

    def fail_run(cmd, check):  # pragma: no cover - 走到这里就是又下载了
        raise AssertionError("不该重复下载同一个视频")

    monkeypatch.setattr(pipeline.subprocess, "run", fail_run)

    video = pipeline.download_video(
        "https://www.bilibili.com/video/BV1qHpY62EoT/", tmp_path
    )
    assert video.read_bytes() == b"cached"
