"""投稿 API：对外提交与查询。

投稿接口**完全开放**（无鉴权），所以校验必须在服务端做足：

- ``type`` / ``title`` / ``payload.items`` 缺一不可
- 空阵容（``items == []``）无意义，400
- 阵型投稿必须给出 ``layout_link`` 或 ``image_path`` 至少一个
- 标题长度上限 100（与 ``submissions.title`` 列宽一致）
"""

from app.content.submissions import SubmissionStatus

VALID = {
    "type": "army_composition",
    "title": "TH16猪流",
    "payload": {
        "th_level": 16,
        "items": [
            {"category": "troop", "name": "Hog Rider", "quantity": 30, "level": 14}
        ],
    },
}


async def _submit(client, payload):
    return await client.post("/api/v1/submissions", json=payload)


# --------------------------------------------------------------------------- #
# 提交
# --------------------------------------------------------------------------- #


async def test_submit_army_composition_returns_pending(client):
    resp = await _submit(client, VALID)
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["status"] == SubmissionStatus.pending.value
    assert body["data"]["type"] == "army_composition"
    assert body["data"]["title"] == "TH16猪流"


async def test_submit_base_layout_returns_pending(client):
    resp = await _submit(client, {
        "type": "base_layout",
        "title": "TH16 阵型",
        "payload": {"th_level": 16, "layout_link": "https://example.com/1"},
    })
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "pending"


async def test_submit_rejects_empty_items_list(client):
    payload = {"type": "army_composition", "title": "x",
               "payload": {"th_level": 16, "items": []}}
    resp = await _submit(client, payload)
    assert resp.status_code == 400, "空阵容无意义"


async def test_submit_rejects_unknown_type(client):
    resp = await _submit(client, {"type": "nonsense", "title": "x", "payload": {}})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMS"


async def test_submit_rejects_empty_title(client):
    resp = await _submit(client, {**VALID, "title": ""})
    assert resp.status_code == 400


async def test_submit_rejects_overlong_title(client):
    resp = await _submit(client, {**VALID, "title": "标" * 101})
    assert resp.status_code == 400


async def test_submit_accepts_title_at_max_length(client):
    resp = await _submit(client, {**VALID, "title": "标" * 100})
    assert resp.status_code == 201


async def test_submit_rejects_missing_payload(client):
    resp = await _submit(client, {"type": "army_composition", "title": "x"})
    assert resp.status_code == 400


async def test_submit_rejects_layout_without_link_or_image(client):
    resp = await _submit(client, {
        "type": "base_layout", "title": "x",
        "payload": {"th_level": 16},
    })
    assert resp.status_code == 400, "阵型必须给 layout_link 或 image_path"


async def test_submit_accepts_layout_with_image_only(client):
    resp = await _submit(client, {
        "type": "base_layout", "title": "x",
        "payload": {"th_level": 16, "image_path": "media/layout/1.png"},
    })
    assert resp.status_code == 201


async def test_submit_rejects_army_composition_without_th_level(client):
    resp = await _submit(client, {
        "type": "army_composition", "title": "x",
        "payload": {"items": [{"category": "troop", "name": "Hog Rider"}]},
    })
    assert resp.status_code == 400


async def test_submit_rejects_items_not_a_list(client):
    resp = await _submit(client, {
        "type": "army_composition", "title": "x",
        "payload": {"th_level": 16, "items": "垃圾"},
    })
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #


async def test_submission_detail_returns_pending_status(client):
    resp = await _submit(client, VALID)
    sub_id = resp.json()["data"]["id"]

    detail = await client.get(f"/api/v1/submissions/{sub_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "pending"


async def test_submission_detail_404_when_missing(client):
    resp = await client.get("/api/v1/submissions/999999")
    assert resp.status_code == 404


async def test_submission_detail_does_not_expose_review_fields(client):
    """对外不暴露 reviewed_by 等内部字段。"""
    resp = await _submit(client, VALID)
    sub_id = resp.json()["data"]["id"]
    body = (await client.get(f"/api/v1/submissions/{sub_id}")).json()
    assert "reviewedBy" not in body["data"]
    assert "reviewedAt" not in body["data"]


async def test_submission_list_is_not_public(client):
    """投稿**没有**列表接口。

    它是后台的工作队列，公开列表等于让任何人翻所有人的投稿。
    要看列表请走后��。"""
    resp = await client.get("/api/v1/submissions")
    assert resp.status_code in (404, 405), "不应存在公开的投稿列表"


async def test_submission_accepts_arbitrary_extra_fields(client):
    """前端可能多带字段，不该因此 422 —— 静默忽略即可。"""
    resp = await _submit(client, {**VALID, "unexpected": "x"})
    assert resp.status_code == 201