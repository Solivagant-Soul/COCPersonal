"""定时采集。

**不得 import FastAPI**（AGENTS.md 架构边界）：``APP_ROLE=collector`` 时本模块要能
脱离 HTTP 层单独起进程。唯一的反向依赖只允许是 app/coc 与 app/db。
"""
