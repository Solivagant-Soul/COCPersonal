"""``app.cli collect``：手动触发一次采集 job。

**为什么要有这条命令**：调度器按 cron 触发（rankings 每 6 小时），刚换好真实
Token 时最长要等 6 小时才有第一批真数据。手动补一次必须**走调度器同一条路径**
（``app.collector.service.run_job``）—— 否则手动跑出来的结果与自动采集的口径
会悄悄分叉（留痕、部分失败记账、令牌桶全都不一样）。
"""

import pytest

from app.cli import build_parser, cmd_collect, main


def test_parser_accepts_known_jobs():
    """job 名从 JOBS 取，拼错必须响亮失败。"""
    parser = build_parser()
    args = parser.parse_args(["collect", "rankings"])
    assert args.command == "collect"
    assert args.job == "rankings"


def test_parser_rejects_unknown_job():
    """拼错的 job 名要立刻报错，而不是等到跑起来才发现。"""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["collect", "no-such-job"])


def test_parser_lists_every_job_in_service():
    """JOBS 里新增的 job 必须自动出现在命令的候选里（不另抄一份名单）。"""
    from app.collector.service import JOBS

    parser = build_parser()
    for job in JOBS:
        assert parser.parse_args(["collect", job]).job == job


async def test_cmd_collect_returns_zero_on_success(monkeypatch, capsys):
    async def fake_run_job(job_name, **kwargs):
        assert job_name == "rankings"
        return "success"

    monkeypatch.setattr("app.collector.service.run_job", fake_run_job)
    assert await cmd_collect("rankings") == 0
    assert "rankings" in capsys.readouterr().out


@pytest.mark.parametrize("status", ["partial", "failed"])
async def test_cmd_collect_returns_nonzero_when_not_fully_successful(
    monkeypatch, capsys, status
):
    """部分失败也算失败 —— 脚本里靠退出码判断，不能把 partial 当成功。"""

    async def fake_run_job(job_name, **kwargs):
        return status

    monkeypatch.setattr("app.collector.service.run_job", fake_run_job)
    assert await cmd_collect("rankings") == 1
    assert status in capsys.readouterr().out


def test_main_dispatches_collect(monkeypatch):
    """``main`` 要把 collect 接到命令上（CLI 的入口只有一个，别漏）。"""

    async def fake_cmd_collect(job: str) -> int:
        assert job == "rankings"
        return 0

    monkeypatch.setattr("app.cli.cmd_collect", fake_cmd_collect)
    assert main(["collect", "rankings"]) == 0
