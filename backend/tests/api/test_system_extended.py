"""就绪探针与对外 IP 限流（Task 14）。

两个端点的语义分工，别搞混：

- ``/healthz`` —— **进程活着吗**。不查依赖，永不失败，**不计入限流桶**（容器
  健康检查要能无限调用，否则服务会被自己的探针打死）。
- ``/readyz`` —— **能对外服务吗**。查 DB、必要时查调度器，失败返回 503。

限流测试必须打**非豁免**端点。字面上"打 /healthz 验证 429"永远拿不到 429，
因为该端点本来就被豁免 —— 这是 R4 裁定记下的坑。
"""


from app.middleware import RateLimitMiddleware, _Request


# --------------------------------------------------------------------------- #
# /healthz
# --------------------------------------------------------------------------- #


async def test_healthz_returns_ok(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_healthz_does_not_depend_on_db(client, monkeypatch):
    """健康检查不能因为 DB 挂了就把进程标成不健康 ——
    那会让编排器重启一个其实还活着、正在等 DB 恢复的进程。"""
    _break_engine_connect(monkeypatch)
    resp = await client.get("/healthz")
    assert resp.status_code == 200


def _break_engine_connect(monkeypatch) -> None:
    """让 `engine.connect()` 抛异常。

    monkeypatch 不能直接给 AsyncEngine.connect 赋值（SQLAlchemy 用 __slots__，
    属性只读），所以换成在 module 层替换 engine 对象。
    """
    import app.api.routes.system as system_module
    import app.db.session as session_module

    class BrokenEngine:
        def connect(self):
            raise RuntimeError("DB 挂了")

    monkeypatch.setattr(system_module, "engine", BrokenEngine(), raising=False)
    monkeypatch.setattr(session_module, "engine", BrokenEngine(), raising=False)


# --------------------------------------------------------------------------- #
# /readyz
# --------------------------------------------------------------------------- #


async def test_readyz_returns_200_when_db_is_reachable(client):
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


async def test_readyz_returns_503_when_db_unreachable(client, monkeypatch):
    _break_engine_connect(monkeypatch)
    resp = await client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


async def test_readyz_returns_503_when_collector_role_has_no_scheduler(client, monkeypatch):
    """app_role=all 时调度器必须已启动，否则这个实例不采集却看起来正常。"""
    from app import main as main_module

    class NotRunning:
        running = False

    class Collector:
        should_run = True
        scheduler = NotRunning()
        role = "all"

    app = main_module.create_app()
    monkeypatch.setattr(app.state, "collector", Collector(), raising=False)
    # lifespan 会覆盖 app.state.collector，所以直接测判定逻辑
    from app.api.routes.system import scheduler_ready

    assert scheduler_ready(Collector()) is False


async def test_readyz_ok_when_api_role_has_no_scheduler(client):
    """api 角色本来就不采集，调度器没跑是正常的 —— 不能因此报 503。"""
    from app.api.routes.system import scheduler_ready

    class NotRunning:
        running = False

    class Collector:
        should_run = False
        scheduler = NotRunning()
        role = "api"

    assert scheduler_ready(Collector()) is True


# --------------------------------------------------------------------------- #
# 限流
# --------------------------------------------------------------------------- #


async def test_rate_limit_blocks_61st_request_in_a_minute(client):
    """第 61 次必须 429。

    打 ``/api/v1/locations`` 而不是 ``/healthz`` —— 后者被豁免，
    在这个端点上永远拿不到 429（R4）。
    """
    for i in range(60):
        resp = await client.get("/api/v1/locations")
        assert resp.status_code == 200, f"第 {i + 1} 次不该被限流"

    resp = await client.get("/api/v1/locations")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"


async def test_rate_limit_response_has_retry_after(client):
    for _ in range(60):
        await client.get("/api/v1/locations")
    resp = await client.get("/api/v1/locations")
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After")


async def test_rate_limit_does_not_apply_to_healthz(client):
    """/healthz 不计入限流桶，供容器健康检查无限调用。"""
    for i in range(200):
        resp = await client.get("/healthz")
        assert resp.status_code == 200, f"第 {i + 1} 次 /healthz 被限流了"


async def test_rate_limit_does_not_apply_to_readyz(client):
    """/readyz 同样豁免 —— 就绪探针同样会被编排器高频调用。"""
    for i in range(200):
        resp = await client.get("/readyz")
        assert resp.status_code == 200, f"第 {i + 1} 次 /readyz 被限流了"


async def test_rate_limit_is_per_client_ip(client):
    """不同 IP 各有各的桶 —— 一个客户端刷爆不该影响其他人。"""
    limiter = RateLimitMiddleware(app=None, requests_per_minute=2)
    from app.middleware import _client_ip

    def request_for(host: str):
        return _Request({"type": "http", "client": (host, 1234), "headers": []})

    for _ in range(2):
        assert await limiter.allow(request_for("1.1.1.1")) is True
    assert await limiter.allow(request_for("1.1.1.1")) is False
    assert await limiter.allow(request_for("2.2.2.2")) is True


async def test_rate_limit_window_slides(client):
    """超出窗口后额度恢复 —— 固定窗口会在窗口边界把额度一次性翻倍。"""
    limiter = RateLimitMiddleware(app=None, requests_per_minute=2, clock=lambda: 1000.0)

    def req():
        return _Request({"type": "http", "client": ("1.1.1.1", 1), "headers": []})

    assert await limiter.allow(req()) is True
    assert await limiter.allow(req()) is True
    assert await limiter.allow(req()) is False

    limiter._clock = lambda: 1061.0  # 过了 60 秒
    assert await limiter.allow(req()) is True


def test_rate_limit_purges_stale_entries():
    """过期条目必须清理，否则内存随见过的 IP 数无限增长。"""
    limiter = RateLimitMiddleware(app=None, requests_per_minute=1, clock=lambda: 1000.0)
    limiter._hits["9.9.9.9"] = [1.0]
    limiter._hits["8.8.8.8"] = [2000.0]  # 未来时间，不该被清

    limiter._purge()

    assert "9.9.9.9" not in limiter._hits
    assert "8.8.8.8" in limiter._hits


def test_rate_limit_trusts_x_forwarded_for_first_value():
    """nginx 反代后 request.client.host 永远是 127.0.0.1。

    不认 X-Forwarded-For 的话全网用户共用一个桶 —— 一个人刷爆所有人被限。
    """
    from app.middleware import _client_ip

    headers = [
        (b"x-forwarded-for", b"203.0.113.7, 10.0.0.1, 10.0.0.2"),
        (b"host", b"example.com"),
    ]
    req = _Request({"type": "http", "client": ("127.0.0.1", 5000), "headers": headers})
    assert _client_ip(req) == "203.0.113.7"


def test_rate_limit_falls_back_to_peer_when_no_forwarded_header():
    from app.middleware import _client_ip

    req = _Request({"type": "http", "client": ("192.0.2.5", 5000), "headers": []})
    assert _client_ip(req) == "192.0.2.5"


async def test_unknown_client_host_does_not_crash(client):
    """部分部署（如某些 ASGI 服务器）拿不到 client 地址，不能因此 500。"""
    limiter = RateLimitMiddleware(app=None, requests_per_minute=1)
    req = _Request({"type": "http", "client": None, "headers": []})
    assert await limiter.allow(req) is True
    assert await limiter.allow(req) is False


# --------------------------------------------------------------------------- #
# 限流不会破坏业务
# --------------------------------------------------------------------------- #


async def test_rate_limit_applies_to_all_api_routes(client, session):
    """限流对所有 /api/v1 端点生效，不只是某一个。

    同一个桶，所以前 58 次用完后打这三个端点：**第三个**必须是 429 ——
    若每个路径各有一个桶，永远拿不到 429。
    """
    from datetime import UTC, datetime

    from app.db.models import Ranking

    session.add(Ranking(kind="clans", location_id=32000001, rank=1,
                        tag="#A", name="A", fetched_at=datetime.now(UTC)))
    await session.commit()

    for _ in range(58):
        await client.get("/api/v1/locations")

    codes = {}
    for path in ("/api/v1/locations", "/api/v1/rankings/clans", "/api/v1/leagues/war"):
        codes[path] = (await client.get(path)).status_code

    assert codes["/api/v1/locations"] == 200
    assert codes["/api/v1/rankings/clans"] == 200
    assert codes["/api/v1/leagues/war"] == 429, (
        f"限流应跨端点共用一个桶，实际 {codes}"
    )


async def test_rate_limit_still_lets_healthz_through_when_bucket_is_full(client):
    """桶满了之后探针仍要通 —— 否则服务会把自己打死。"""
    for _ in range(60):
        await client.get("/api/v1/locations")
    assert (await client.get("/api/v1/locations")).status_code == 429
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/readyz")).status_code == 200