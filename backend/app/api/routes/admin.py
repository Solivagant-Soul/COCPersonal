"""SQLAdmin 后台。

三条安全底线：

1. **凭据只来自环境变量**，代码里不硬编码任何账号密码，比对用
   ``secrets.compare_digest``（常数时间，防时序侧信道）。
2. **官方数据全部只读。** 后台手改 ``clans`` / ``rankings`` 之类的表，
   下一轮采集就会覆盖 —— 而覆盖前的那个错值已经被人看过了。
3. **采集表不注册。** 让管理员删掉 ``locations`` 或 ``seasons`` 的话，
   采集会静默地写不进去（不会报错，只是数据永远不对）。

登录方式是 Starlette 的 ``AuthenticationBackend``：登录表单提交后拿到
``base64(username:password)`` 的 token，之后每个请求都会重新比对一遍。
所以 ``admin_username`` / ``admin_password`` 每次都从环境变量读，
改 ``.env`` 后重启即生效。
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Optional

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.db.models import (
    Announcement,
    ArmyComposition,
    ArmyCompositionItem,
    BaseLayout,
    Clan,
    CollectorRun,
    Player,
    Ranking,
    Submission,
    UpgradeItem,
    UpgradeRoute,
    UpgradeRouteStep,
)

logger = logging.getLogger("coc.admin")


class AdminAuth(AuthenticationBackend):
    """单一管理员账号，凭据来自环境变量。

    **不入库、无角色模型**（一期只有一个人管后台）。规格里不存在管理员表，
    也不该有 —— 那等于凭空造一张没人设计过的表。

    SQLAdmin 的认证是 **session-based**：登录成功时把用户名写进签名 cookie，
    之后每个请求由 :meth:`authenticate` 校验签名 cookie 里那份凭据是否仍与
    环境变量一致。所以改 ``.env`` 后**不需要重启**就能把旧会话踢掉 ——
    比对每次请求都重新做。
    """

    #: session 里存用户名的键
    SESSION_KEY = "admin_username"

    def __init__(self, secret_key: str) -> None:
        super().__init__(secret_key=secret_key)

    @property
    def admin_username(self) -> str:
        return os.environ.get("ADMIN_USERNAME", "")

    @property
    def admin_password(self) -> str:
        return os.environ.get("ADMIN_PASSWORD", "")

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        # compare_digest 是常数时间：普通字符串比较会因短路比较在首个不同字符
        # 处返回，理论上可被时序侧信道逐字节试出密码
        ok = secrets.compare_digest(username, self.admin_username) and (
            secrets.compare_digest(password, self.admin_password)
        )
        if not ok:
            logger.warning("后台登录失败：用户名或密码不对")
            return False
        request.session[self.SESSION_KEY] = username
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        username = request.session.get(self.SESSION_KEY)
        if not username:
            return False
        # 每次请求都比对环境变量：改完 .env 立刻生效，旧 cookie 自动失效
        return secrets.compare_digest(str(username), self.admin_username) and bool(
            self.admin_password
        )

    async def get_user_id(self, request: Request) -> Optional[str]:
        """审计与授权后端读的"当前操作者"。"""
        return request.session.get(self.SESSION_KEY)


# --------------------------------------------------------------------------- #
# 只读视图：官方数据与运行记录
# --------------------------------------------------------------------------- #


class _ReadOnlyView(ModelView):
    """官方数据的统一视图：**只能看**。

    手改 ``clans`` / ``rankings`` 的后果不是"改错了会被发现"，而是
    "改错的值在被覆盖之前已经被人看见并拿去提问了"。
    """

    can_create = False
    can_edit = False
    can_delete = False
    can_export = False


class ClanView(_ReadOnlyView, model=Clan):
    name = "部落"
    name_plural = "部落"
    column_list = ["tag", "name", "level", "trophies", "member_count", "fetched_at"]
    column_searchable_list = ["tag", "name"]
    column_filters = ["level"]


class PlayerView(_ReadOnlyView, model=Player):
    name = "玩家"
    name_plural = "玩家"
    column_list = ["tag", "name", "exp_level", "trophies", "clan_tag", "fetched_at"]
    column_searchable_list = ["tag", "name"]
    column_filters = ["exp_level"]


class RankingView(_ReadOnlyView, model=Ranking):
    name = "排行榜条目"
    name_plural = "排行榜条目"
    column_list = ["kind", "location_id", "rank", "tag", "name", "fetched_at"]
    column_searchable_list = ["tag", "name"]
    column_filters = ["kind", "location_id"]


class CollectorRunView(_ReadOnlyView, model=CollectorRun):
    name = "采集运行记录"
    name_plural = "采集运行记录"
    column_list = [
        "job_name", "status", "started_at", "finished_at",
        "items_total", "items_ok", "items_failed",
    ]
    column_details_exclude_list = ["error"]
    column_filters = ["job_name", "status"]
    column_default_sort = [(CollectorRun.started_at, False)]


# --------------------------------------------------------------------------- #
# 可编辑视图：内容数据
# --------------------------------------------------------------------------- #


class AnnouncementView(ModelView, model=Announcement):
    """公告。录入、发布、置顶都在这里。"""

    name = "公告"
    name_plural = "公告"
    can_create = True
    can_edit = True
    can_delete = True
    column_list = [
        "title", "category", "is_pinned", "is_published", "published_at",
    ]
    column_searchable_list = ["title", "body"]
    column_filters = ["category", "is_pinned", "is_published"]
    # created_at / updated_at 由后台自动填，不该被手改
    form_excluded_columns = ["created_at", "updated_at"]
    column_default_sort = [(Announcement.is_pinned, False)]


class UpgradeItemView(ModelView, model=UpgradeItem):
    """升级条目。

    **可编辑的唯一理由是补 ``name_zh`` 与 ``builder_count``** —— 导入阶段
    这两列恒为 NULL（不猜翻译），人工标注后不许被重跑冲掉
    （``import_upgrade_items`` 的 upsert 不含这两列）。
    """

    name = "升级条目"
    name_plural = "升级条目"
    can_create = False
    can_edit = True
    can_delete = False
    column_list = [
        "category", "name", "name_zh", "village", "level",
        "gold", "elixir", "dark_elixir", "build_time_seconds", "builder_count",
    ]
    column_searchable_list = ["name", "name_zh"]
    column_filters = ["category", "village"]
    column_default_sort = [(UpgradeItem.category, False), (UpgradeItem.name, False)]


class UpgradeRouteView(ModelView, model=UpgradeRoute):
    name = "升级路线"
    name_plural = "升级路线"
    can_create = True
    can_edit = True
    can_delete = True
    column_list = ["name", "name_zh", "description", "created_at"]
    column_searchable_list = ["name", "name_zh"]
    # created_at 是审计字段，不该在表单里改
    form_excluded_columns = ["created_at"]


class SubmissionView(ModelView, model=Submission):
    """投稿：只读列表 + 通过/驳回两个动作。

    内容**只能**由审核流程创建 —— 直接编辑投稿会绕过 ``approve_submission``
    的校验（空 items、缺 layout_link 等）与幂等保护。
    """

    name = "投稿"
    name_plural = "投稿"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        "type", "title", "status", "created_at", "reviewed_at", "reviewed_by",
    ]
    column_searchable_list = ["title"]
    column_filters = ["type", "status"]
    column_default_sort = [(Submission.created_at, False)]
    row_actions = ["approve", "reject"]

    async def approve(self, request: Request):
        """通过：调业务层，不在这里重复校验逻辑。"""
        from app.content.submissions import approve_submission

        submission = await self.get_object_for_edit(request)
        async with self.session_maker(request) as session:
            obj = await session.get(Submission, submission.id)
            await approve_submission(session, obj, reviewer="admin")
            await session.commit()
        return self.tooltip_success("已通过")

    async def reject(self, request: Request):
        from app.content.submissions import SubmissionStatus

        submission = await self.get_object_for_edit(request)
        async with self.session_maker(request) as session:
            obj = await session.get(Submission, submission.id)
            obj.status = SubmissionStatus.rejected
            await session.commit()
        return self.tooltip_success("已驳回")


class ArmyCompositionView(_ReadOnlyView, model=ArmyComposition):
    """阵容：内容来自投稿审核或后台录入，一期只读。"""

    name = "阵容"
    name_plural = "阵容"
    column_list = [
        "title", "th_level", "source_site", "copy_count", "is_published",
    ]
    column_searchable_list = ["title"]
    column_filters = ["th_level", "is_published"]


class ArmyCompositionItemView(_ReadOnlyView, model=ArmyCompositionItem):
    name = "阵容明细"
    name_plural = "阵容明细"
    column_list = ["composition_id", "position", "category", "name", "level",
                   "quantity"]
    column_filters = ["category"]


class BaseLayoutView(_ReadOnlyView, model=BaseLayout):
    name = "阵型"
    name_plural = "阵型"
    column_list = [
        "title", "th_level", "layout_link", "image_path",
        "source_site", "copy_count", "is_published",
    ]
    column_searchable_list = ["title"]
    column_filters = ["th_level", "is_published"]


#: 注册到后台的模型。**刻意不含**维表与战场表（Location / LeagueTier /
#: League / Label / Season / ClanMember / ClanWar / ClanWarLog / Cwl*）——
#: 它们由采集任务拥有，管理员误删会导致采集静默失效。
REGISTERED_MODELS: tuple[type, ...] = (
    Announcement,
    Submission,
    ArmyComposition,
    ArmyCompositionItem,
    BaseLayout,
    UpgradeItem,
    UpgradeRoute,
    UpgradeRouteStep,
    Clan,
    Player,
    Ranking,
    CollectorRun,
)


def build_admin(app, engine, settings) -> Admin:
    """构造并挂载后台。

    ``engine`` 传进来而不是在这里新建：与 app 用同一个池，
    测试里也能复用同一套 fixture。
    """
    admin = Admin(
        app,
        engine=engine,
        base_url="/admin",
        title="COC 后台",
        authentication_backend=AdminAuth(secret_key=settings.admin_secret_key),
    )
    for view in (
        AnnouncementView,
        SubmissionView,
        ArmyCompositionView,
        ArmyCompositionItemView,
        BaseLayoutView,
        UpgradeItemView,
        UpgradeRouteView,
        ClanView,
        PlayerView,
        RankingView,
        CollectorRunView,
    ):
        admin.add_view(view)
    return admin