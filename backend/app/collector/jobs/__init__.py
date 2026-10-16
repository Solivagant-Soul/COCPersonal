"""采集 job 实现。

每个模块的形状统一为 ``async def collect_x(client, session) -> dict[str, int]``，
由 :mod:`app.collector.service` 统一包上运行记录与状态判定。

**本包不得 import FastAPI 或 app.api**（AGENTS.md 架构边界）——
``APP_ROLE=collector`` 时要能脱离 HTTP 层单独起进程。
"""