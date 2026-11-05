from pathlib import Path

import pipeline
from bili_links import (
    _collect_texts,
    extract_opus_ids,
    extract_pinned_texts,
    normalize_layout_link,
    parse_layout_codes,
)
from pipeline import frame_timestamps, missing_numbers

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


def test_extract_opus_ids_dedupes_and_keeps_order():
    texts = [
        "链接在 https://www.bilibili.com/opus/111 里",
        "再贴一次 https://www.bilibili.com/opus/111",
        "备用 https://bilibili.com/opus/222?share=1",
    ]
    assert extract_opus_ids(texts) == ["111", "222"]


def test_collect_texts_walks_nested_rich_text_nodes():
    payload = {
        "item": {
            "modules": {
                "module_dynamic": {
                    "desc": {"text": "总览", "rich_text_nodes": [{"text": "1号：TH18:WB:AAA"}]},
                    "major": {"opus": {"title": "18本阵型", "summary": {"text": "第二段"}}},
                }
            }
        }
    }
    texts = _collect_texts(payload)
    assert "1号：TH18:WB:AAA" in texts
    assert "18本阵型" in texts
    assert "第二段" in texts


def test_missing_numbers_honours_mapping():
    links = {1: "a", 3: "c"}
    assert missing_numbers(links, 3, {}) == [2]
    # 第 2 个抽帧映射到链接 3 后，就不缺号了
    assert missing_numbers(links, 3, {2: 3}) == []


def test_load_links_dumps_raw_when_notes_are_images(tmp_path, monkeypatch):
    """置顶是图片笔记（没有正文）时，原始响应要落盘供人工看图。"""
    monkeypatch.setattr(
        pipeline.bili_links, "fetch_pinned", lambda bvid, cookies: ["看笔记 https://www.bilibili.com/opus/42"]
    )
    monkeypatch.setattr(
        pipeline.bili_links,
        "fetch_opus",
        lambda opus_id, cookies: {"texts": [], "raw": {"pics": ["https://i0.hdslb.com/a.jpg"]}},
    )

    links, raw_text, from_file = pipeline.load_links(None, "cookies.txt", "BV1qHpY62EoT")

    assert links == {}
    assert from_file is False
    target = pipeline.write_raw(tmp_path, raw_text)
    body = target.read_text(encoding="utf-8")
    assert "opus/42" in body
    assert "a.jpg" in body


def test_load_links_parses_note_body(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pipeline.bili_links, "fetch_pinned", lambda bvid, cookies: ["https://www.bilibili.com/opus/7"]
    )
    monkeypatch.setattr(
        pipeline.bili_links,
        "fetch_opus",
        lambda opus_id, cookies: {"texts": [f"1号：{CODE}"], "raw": {}},
    )

    links, _, from_file = pipeline.load_links(None, "cookies.txt", "BV1qHpY62EoT")

    assert from_file is False
    assert links[1] == BASE + "TH18%3AWB%3AAAAARAAAAAAphHQWN6eIhzQedsGoEvXp"


def test_load_links_reads_comments_file_without_cookies(tmp_path):
    """没有 cookie 时，把置顶正文存成本地文本也能跑（离线兜底）。"""
    note = tmp_path / "note.txt"
    note.write_text(f"1号：{CODE}", encoding="utf-8")

    links, raw_text, from_file = pipeline.load_links(
        None, "不存在的 cookie.txt", "BV1qHpY62EoT", str(note)
    )

    assert from_file is False
    assert links[1] == BASE + "TH18%3AWB%3AAAAARAAAAAAphHQWN6eIhzQedsGoEvXp"
    assert raw_text == f"1号：{CODE}"


def _argv(tmp_path: Path) -> list[str]:
    return [
        "--video-url",
        "https://www.bilibili.com/video/BV1qHpY62EoT/",
        "--count",
        "2",
        "--workdir",
        str(tmp_path),
        "--dry-run",
    ]


def test_main_stops_and_dumps_raw_when_nothing_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.bili_links, "fetch_pinned", lambda bvid, cookies: ["好阵型"])

    rc = pipeline.main(_argv(tmp_path))

    assert rc == 1
    assert (tmp_path / "links.raw.txt").read_text(encoding="utf-8").strip() == "好阵型"


def test_main_stops_when_numbers_are_missing(tmp_path, monkeypatch):
    """缺号直接停：半套数据传上去再补，比现在停下来更麻烦。"""
    monkeypatch.setattr(
        pipeline.bili_links, "fetch_pinned", lambda bvid, cookies: [f"1号：{CODE}"]
    )

    rc = pipeline.main(_argv(tmp_path))

    assert rc == 1
    assert (tmp_path / "links.raw.txt").is_file()
