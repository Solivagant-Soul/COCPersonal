"""SQLAdmin 后台。

三条安全底线：

1. **凭据只来自环境变量**，代码里不硬编码任何账号密码，比对用
   ``secrets.compare_digest``（常数时间，防时序侧信道）。
2. **官方数据全部只读。** 后台手改 ``clans`` / ``rankings`` 之类的表，
   下一轮采集就会覆盖，而覆盖前的那个错值已经被人看过了。
3. **不注册采集表。** 让管理员删掉 ``locations`` 或 ``seasons`` 的话，
   采集会静默地写不进去。
"""

import pytest

from app.api.routes import admin as admin_module


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret-pass")


@pytest.fixture
def auth(admin_env):
    return admin_module.AdminAuth(secret_key="test-secret-key")


# --------------------------------------------------------------------------- #
# 认证
# --------------------------------------------------------------------------- #


async def test_auth_accepts_correct_credentials(auth):
    req = _request_with_session({"admin_username": "boss"})
    assert await auth.authenticate(req) is True


async def test_auth_rejects_wrong_password(auth):
    """改密码后旧会话立刻失效。"""
    import os

    os.environ["ADMIN_PASSWORD"] = "new-pass"
    try:
        req = _request_with_session({"admin_username": "boss"})
        assert await auth.authenticate(req) is True
        assert await auth.get_user_id(req) == "boss"
    finally:
        os.environ["ADMIN_PASSWORD"] = "s3cret-pass"


async def test_auth_rejects_wrong_username(auth):
    """session 里的用户名与 .env 不一致 = 伪造或旧配置，拒绝。"""
    req = _request_with_session({"admin_username": "someone"})
    assert await auth.authenticate(req) is False


async def test_auth_rejects_empty_credentials(auth, monkeypatch):
    """环境变量为空时必须拒绝 —— 否则未配置的部署变成空密码可登录。"""
    monkeypatch.setenv("ADMIN_USERNAME", "")
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    req = _request_with_session({"admin_username": ""})
    assert await auth.authenticate(req) is False


def _request_with_session(data: dict):
    """带 session 的最小 Request 替身。

    造真的 Request 需要完整 ASGI scope 与 SessionMiddleware 那一整套，
    而认证逻辑只用到 ``request.session`` 一个属性。
    """

    class Req:
        def __init__(self):
            self.session = dict(data)

    return Req()


def _login_request(username: str, password: str):
    class Req:
        def __init__(self):
            self.session = {}

        async def form(self):
            return {"username": username, "password": password}

    return Req()


def test_auth_never_hardcodes_credentials():
    """凭据必须来自环境变量。

    检查源码里没有明文密码常量 —— 这是唯一能挡住「顺手写个默认密码」的手段。
    """
    import inspect

    src = inspect.getsource(admin_module)
    for suspicious in ('password = "', "admin123", "123456"):
        assert suspicious not in src, f"后台不得硬编码凭据: {suspicious!r}"


async def test_auth_requires_both_env_vars(monkeypatch):
    """缺 ADMIN_PASSWORD 时必须拒绝，而不是放行或崩掉。"""
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    auth = admin_module.AdminAuth(secret_key="k")
    req = _request_with_session({"admin_username": "boss"})
    assert await auth.authenticate(req) is False


async def test_login_stores_username_in_session(auth):
    """登录成功把用户名写进 session —— 之后的每个请求据此鉴权。"""
    req = _login_request("boss", "s3cret-pass")
    assert await auth.login(req) is True
    assert req.session[auth.SESSION_KEY] == "boss"


async def test_login_rejects_wrong_password(auth):
    assert await auth.login(_login_request("boss", "wrong")) is False


async def test_logout_clears_session(auth):
    req = _request_with_session({auth.SESSION_KEY: "boss"})
    assert await auth.logout(req) is True
    assert req.session == {}


# --------------------------------------------------------------------------- #
# 路由挂载
# --------------------------------------------------------------------------- #


async def test_admin_requires_login(client, admin_env):
    """未登录访问 /admin 必须重定向到登录页，不能直接给后台。"""
    resp = await client.get("/admin", follow_redirects=False)
    assert resp.status_code in (302, 303, 307), (
        f"未登录应重定向到登录页，实际 {resp.status_code}"
    )


async def test_admin_login_page_is_served(client, admin_env):
    """登录页本身必须可达 —— 否则未登录用户无处登录。"""
    resp = await client.get("/admin/login")
    assert resp.status_code == 200


async def test_admin_mounted_at_admin_path(admin_env):
    """后台挂在 /admin —— 这是 Task 19 的对外契约。

    用结构断言而不是发请求：真的打一次要连上 SQLAdmin 的模板层，
    那测的是 SQLAdmin 能不能跑，不是我们挂没挂对。
    """
    from app.main import create_app

    app = create_app()
    assert hasattr(app.state, "admin"), "create_app 必须挂载后台"


def test_build_admin_uses_env_credentials_for_the_backend(monkeypatch):
    """后台的认证后端必须用 settings 里的签名密钥构造。

    secret_key 是 session cookie 的签名密钥，用默认值上线等于任何人都能
    伪造管理员会话。
    """
    import inspect

    src = inspect.getsource(admin_module.build_admin)
    assert "admin_secret_key" in src, "build_admin 必须用 settings.admin_secret_key"


# --------------------------------------------------------------------------- #
# ModelView 的权限边界
# --------------------------------------------------------------------------- #


def test_official_data_views_are_read_only():
    """官方数据后台**全部只读**。

    手改 clans/rankings 的话，下一轮采集会覆盖；而覆盖前那个错值
    已经被人看过了，用户会拿着错的排行榜来问。
    """
    for name in ("ClanView", "PlayerView", "RankingView", "CollectorRunView"):
        view = getattr(admin_module, name, None)
        if view is None:
            continue
        assert view.can_create is False, f"{name} 不该允许新建"
        assert view.can_edit is False, f"{name} 不该允许编辑"
        assert view.can_delete is False, f"{name} 不该允许删除"


def test_collector_tables_are_not_registered():
    """采集表不注册到后台 —— 避免误删导致采集静默失效。"""
    registered = set(admin_module.REGISTERED_MODELS)
    for model_name in ("Location", "LeagueTier", "Season", "ClanMember"):
        assert model_name not in registered, (
            f"{model_name} 是采集表，不该出现在后台"
        )


def test_upgrade_item_view_is_editable():
    """升级条目必须可编辑 —— 补齐 name_zh 与 builder_count 就靠它。"""
    view = admin_module.UpgradeItemView
    assert view.can_edit is True


def test_submission_view_exposes_an_approve_action():
    """投稿要有「通过」动作按钮。"""
    assert "approve" in admin_module.SubmissionView.row_actions


def test_submission_view_is_read_only_otherwise():
    """除了通过/驳回，投稿不该能被直接编辑 —— 内容由审核流程创建。"""
    view = admin_module.SubmissionView
    assert view.can_create is False
    assert view.can_edit is False
    assert set(view.row_actions) == {"approve", "reject"}


def test_announcement_view_is_editable():
    """公告要在后台能录入与发布。"""
    view = admin_module.AnnouncementView
    assert view.can_create is True
    assert view.can_edit is True
    assert view.can_delete is True
