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
