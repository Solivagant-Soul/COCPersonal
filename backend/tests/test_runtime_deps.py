"""生产镜像只装 ``pyproject.toml`` 里声明过的依赖；本机环境却多得多。

**这个差别已经咬过一次人**：SQLAdmin 的 ``AuthenticationBackend`` 需要 starlette 的
``SessionMiddleware``，后者在函数内 ``import itsdangerous``。``itsdangerous`` 既不是
starlette/sqladmin 的硬依赖（它在 starlette 的 extra 里），我们也没显式声明它 ——
于是**本机 501 个测试全绿**（本机环境里恰好装着它），**生产镜像里却在导入期就
``ModuleNotFoundError``**，容器启动即 exit 1，进入重启循环。

所以本测试不复现「本机装了什么」，而是**复现镜像里有什么**：

1. 读 ``pyproject.toml`` 的 ``dependencies`` → 已声明的发行包；
2. 顺着 ``importlib.metadata.requires()`` 求出它们的**传递依赖闭包** → 镜像里会有的全部包；
3. 本机装着的、但**不在闭包内**的包 → 「孤儿包」，镜像里**没有**；
4. 起一个子进程，用 ``MetaPathFinder`` 把孤儿包提供的顶层模块**全部屏蔽**，
   然后 ``import app.main`` —— 相当于在镜像里 import 一次应用。

镜像里必然缺的东西，在这里也会缺 → 测试失败，且报错信息直接指出缺哪个模块。
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, packages_distributions, requires
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

#: ``uvicorn[standard]`` → ``uvicorn``；``foo>=1.2; python_version<"3.11"`` → ``foo``
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9._-]+)")


def _normalize(name: str) -> str:
    """发行包名归一化：``SQLAlchemy`` / ``sql_alchemy`` → ``sqlalchemy``。"""
    return name.lower().replace("_", "-")


def _declared_distributions() -> set[str]:
    """``pyproject.toml`` 里显式声明的发行包 **+ 项目自己**。

    项目自己必须算进去：镜像里装的就是它。漏了它，源码树里任何 ``*.egg-info``
    构建残留都会让 ``packages_distributions()`` 把 ``app`` 映射成一个「未声明的孤儿包」，
    守卫会连应用自己一起屏蔽掉（这是本守卫写出来后真踩到的一次误报）。
    """
    data = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    out = {_normalize(data["project"]["name"])}
    for dep in deps:
        match = _REQ_NAME.match(dep)
        assert match, f"解析不了依赖声明：{dep!r}"
        out.add(_normalize(match.group(1)))
    return out


def _requirement_applies(req_text: str) -> bool:
    """这条 requirement 在「不装任何 extra」时是否成立。

    **extras 必须排除**：`pip install .` 不会装 extra 里的包，而
    ``fastapi`` 的 ``itsdangerous`` 恰恰挂在 ``extra == "all"`` 下、
    ``sqladmin`` 的挂在 ``extra == 'auth'`` 下 —— 把它们算进闭包，
    就等于假装镜像里有它们（正是本 bug 的成因）。
    """
    try:
        from packaging.requirements import Requirement
    except ModuleNotFoundError:  # pragma: no cover - packaging 是 pytest 的依赖
        return "extra" not in req_text.split(";", 1)[-1]

    try:
        req = Requirement(req_text)
    except Exception:  # pragma: no cover - 解析不了的写法按「适用」处理
        return True
    if req.marker is None:
        return True
    try:
        # extra="" 表示「没请求任何 extra」
        return bool(req.marker.evaluate({"extra": ""}))
    except Exception:  # pragma: no cover
        return True


def _transitive_closure(declared: set[str]) -> set[str]:
    """已声明包 + 它们传递要求的所有包 = 镜像里会存在的包。

    只跟**基础依赖**，不跟 extra（``uvicorn[standard]`` 的 extra 不会随 ``pip install .`` 装上）——
    这正是本 bug 的成因之一，所以这里必须严格按「镜像实际有什么」算。
    """
    seen = set(declared)
    frontier = list(declared)
    while frontier:
        dist = frontier.pop()
        try:
            requirements = requires(dist) or []
        except PackageNotFoundError:  # pragma: no cover - 本机没装这个包
            continue
        for req in requirements:
            match = _REQ_NAME.match(req)
            if not match:
                continue
            if not _requirement_applies(req):
                continue
            name = _normalize(match.group(1))
            if name not in seen:
                seen.add(name)
                frontier.append(name)
    return seen


def _orphan_modules(closure: set[str]) -> list[str]:
    """本机装了、但镜像里不会有（不在闭包内）的包所提供的顶层模块。

    只有当某个模块的**所有**提供方都是孤儿包时才屏蔽它 —— 否则会误伤
    （比如 ``typing_extensions`` 可能同时由多个包提供）。
    """
    module_to_dists = packages_distributions()
    orphan_dists = {
        dist
        for dists in module_to_dists.values()
        for dist in dists
        if _normalize(dist) not in closure
    }
    blocked = []
    for module, dists in module_to_dists.items():
        if dists and all(_normalize(d) in orphan_dists for d in dists):
            blocked.append(module)
    return sorted(blocked)


def _app_imports_third_party_modules() -> set[str]:
    """``app/`` 里 import 的第三方顶层模块（静态清单，供人工核对用）。"""
    import sys as _sys

    found = set()
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return {m for m in found if m not in _sys.stdlib_module_names and m != "app"}


RUNNER = """
import sys

BLOCKED = set(json.loads(sys.argv[1]))


class Blocker:
    \"\"\"把「本机有、镜像里没有」的模块挡在 import 之前。\"\"\"

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(
                f"No module named {fullname!r} (blocked: 不在 pyproject 声明的依赖闭包内)"
            )
        return None


sys.meta_path.insert(0, Blocker())

import app.main  # noqa: F401  —— 模块级就调用了 create_app()
print("OK")
"""


def test_app_imports_with_only_declared_dependencies() -> None:
    """应用必须能在「只有已声明依赖」的环境里 import 并构造出来。

    这条守的是**镜像与本机环境的差异**——本机多出来的孤儿包会让测试全绿，
    却让容器在导入期就崩。
    """
    closure = _transitive_closure(_declared_distributions())
    blocked = _orphan_modules(closure)
    assert blocked, "孤儿包清单为空：检查 packages_distributions() 是否可用"

    runner = BACKEND_DIR / "_tmp_dep_guard_runner.py"
    runner.write_text(
        "import json\n" + RUNNER, encoding="utf-8"
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(runner), json.dumps(blocked)],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        runner.unlink(missing_ok=True)

    assert proc.returncode == 0, (
        "应用在「只有已声明依赖」的环境里 import 失败 —— 生产镜像会在这里崩：\n"
        f"{proc.stderr.strip()[-3000:]}\n"
        f"（被屏蔽的孤儿模块共 {len(blocked)} 个，其中含真正需要的依赖时，"
        f"请把它显式声明进 pyproject.toml 的 dependencies）"
    )


def test_declared_dependencies_cover_runtime_imports() -> None:
    """``app/`` 直接 import 的第三方模块，要么被声明，要么由已声明包提供。

    与上一条互补：上一条抓「声明缺失」，这条抓「声明了但用不上」这类反向问题
    （例如误把标准库模块写进 dependencies）。
    """
    closure = _transitive_closure(_declared_distributions())
    module_to_dists = packages_distributions()
    missing = []
    for module in sorted(_app_imports_third_party_modules()):
        dists = module_to_dists.get(module)
        if not dists:
            continue  # 没有发行包元数据（标准库/命名空间包），不判
        if not any(_normalize(d) in closure for d in dists):
            missing.append(f"{module}（提供方 {sorted(dists)}）")
    assert not missing, "这些模块没被任何已声明依赖覆盖：" + "；".join(missing)


#: 夹具文件名 → 必须随包分发的清单
FIXTURE_FILES = (
    "clan_detail.json",
    "player_profile.json",
    "locations.json",
    "ranking_clans.json",
    "coc_units_mini.json",
)


def test_fixtures_are_packaged_with_the_app() -> None:
    """夹具是**运行时资产**（无 Token 时由夹具上游应答），必须在包内并随 wheel 分发。

    镜像里应用是 ``pip install .`` 装进 site-packages 的，``tests/`` 根本不进镜像 ——
    夹具放在 ``tests/fixtures/`` 时，**无 Token 的部署里所有上游读取都 FileNotFoundError**
    （``seed-dev-rankings`` 同样报错）。这条已经真实发生过两次。
    """
    import app.coc
    from app.coc.devfixtures import FIXTURES_DIR

    package_dir = Path(app.coc.__file__).resolve().parent
    assert FIXTURES_DIR.is_relative_to(package_dir), (
        f"夹具目录必须在包内（{package_dir} 之下），当前是 {FIXTURES_DIR}"
    )
    for name in FIXTURE_FILES:
        path = FIXTURES_DIR / name
        assert path.is_file(), f"夹具缺失：{path}"

    # 还得声明成 package-data，否则 wheel 里没有它们（源码树里有 ≠ 装出来有）
    data = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"].get("package-data", {})
    globs = package_data.get("app.coc", [])
    assert any("fixtures" in g for g in globs), (
        "pyproject.toml 的 [tool.setuptools.package-data] 必须为 app.coc 声明 "
        f"fixtures/*.json，当前是 {globs}"
    )
