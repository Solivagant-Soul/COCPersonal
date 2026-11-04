"""阵型视频导入流水线。

本文件同时是 CLI 入口（Task 8 起）；纯逻辑放前面，方便单测直接 import。
"""

from __future__ import annotations


def frame_timestamps(duration: float, count: int) -> list[float]:
    """把 ``duration`` 秒等分成 ``count`` 段，返回每段靠前 20% 的时间点。

    视频里每个阵型停留时长基本一致（本片约 3s/个），没有转场检测也够用；
    取段首 20% 是为了避开换阵瞬间的过场动画。``--mapping`` 用来兜底修正。
    """
    if count <= 0:
        return []
    interval = duration / count
    return [i * interval + interval * 0.2 for i in range(count)]
