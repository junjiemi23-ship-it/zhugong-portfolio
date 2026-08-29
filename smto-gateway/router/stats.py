"""
路由统计（2026-08-29 观测性增强）：把网关从"黑盒"变成"可事后复盘"。

只加信息、不改行为 —— 路由核心逻辑零改动，本模块任何异常都不允许冒泡到请求路径。

设计红线（实现时逐条落实）：
1. 内存有界：换腿历史用 deque(maxlen=500) 环形缓冲，超出自动丢最旧；
   每腿计数 dict 以候选腿数为上限（~29 条），不会无限增长。
2. 口径定死（见 snapshot() 文档）：所有计数均为「自本网关进程启动以来」，
   重启清零；窗口语义配合 /health 的 uptime_seconds 解读。
3. 只记元数据：provider/model、错误类别、状态码、耗时 —— 绝不记录消息内容。
4. 热路径零风险：所有公开函数内部 try/except 包裹，统计失败静默降级，
   绝不影响路由；锁为 threading.Lock（reprobe 后台线程与事件循环共用）。

口径速查（snapshot 返回值）：
- requests: 请求级计数。routed_total=进入候选链尝试的总次数;
  ok_first_leg=首腿即成功; ok_after_switch=换腿后成功; failed_all=全链耗尽(502)。
- legs: 按 "provider/model" 聚合。attempts=实际调用次数(冷却跳过不计);
  successes/failures; failures_by_category={rate_limited: n, auth: n, ...};
  avg_ms=成功请求平均耗时。
- switches: 最近换腿事件（新→旧）。t=Unix 秒, from/to=腿键,
  reason="category(status)"，如 "rate_limited(429)"。
- events: 其他值得注意的事件（如 reprobe_recovered：后台复探提前解封 provider）。
"""

import logging
import threading
from collections import deque
from time import time
from typing import Any

logger = logging.getLogger("harness_router.stats")

SWITCH_HISTORY_MAX = 500  # 环形缓冲上限（条）


class RouteStats:
    """线程安全的进程内路由统计。所有公开方法吞异常，永不影响调用方。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time()
        # 请求级计数
        self._req = {
            "routed_total": 0,
            "ok_first_leg": 0,
            "ok_after_switch": 0,
            "failed_all": 0,
        }
        # 每腿计数: "provider/model" -> {attempts, successes, failures, failures_by_category, ms_total}
        self._legs: dict[str, dict[str, Any]] = {}
        # 换腿历史（环形）+ 杂项事件（环形，共用上限预算的独立 deque）
        self._switches: deque[dict[str, Any]] = deque(maxlen=SWITCH_HISTORY_MAX)
        self._events: deque[dict[str, Any]] = deque(maxlen=SWITCH_HISTORY_MAX)

    # ------------------------------------------------------------------
    # 记录接口（热路径调用；内部吞掉一切异常）
    # ------------------------------------------------------------------

    def record_route(
        self,
        task_type: str,
        path: list[tuple[str, bool, str | None, int | None]],
        final_ms: float | None = None,
    ) -> None:
        """记录一次完整的候选链尝试。

        path: 按尝试顺序的元组列表 [(leg_key, ok, category, status), ...]
        - 最后一个 ok=True → 该请求成功（首腿成功 or 换腿后成功）
        - 全部 ok=False    → 全链耗尽（网关返回 502）
        换腿事件从 path 中相邻的 (失败腿 → 下一腿) 推导，无需调用方显式上报。
        """
        try:
            if not path:
                return
            with self._lock:
                self._req["routed_total"] += 1
                last_ok = bool(path[-1][1])
                if last_ok and len(path) == 1:
                    self._req["ok_first_leg"] += 1
                elif last_ok:
                    self._req["ok_after_switch"] += 1
                else:
                    self._req["failed_all"] += 1

                for i, (leg, ok, category, status) in enumerate(path):
                    leg_stat = self._legs.setdefault(leg, {
                        "attempts": 0, "successes": 0, "failures": 0,
                        "failures_by_category": {}, "ms_total": 0.0, "ms_count": 0,
                    })
                    leg_stat["attempts"] += 1
                    if ok:
                        leg_stat["successes"] += 1
                        if final_ms is not None:
                            leg_stat["ms_total"] += final_ms
                            leg_stat["ms_count"] += 1
                    else:
                        leg_stat["failures"] += 1
                        cat = category or "unknown"
                        leg_stat["failures_by_category"][cat] = (
                            leg_stat["failures_by_category"].get(cat, 0) + 1
                        )
                    # 推导换腿：本腿失败且后面还有下一腿
                    if not ok and i + 1 < len(path):
                        nxt = path[i + 1][0]
                        reason = f"{category or 'unknown'}({status})" if status else (category or "unknown")
                        self._switches.appendleft({
                            "t": round(time()),
                            "task_type": task_type,
                            "from": leg,
                            "to": nxt,
                            "reason": reason,
                        })
        except Exception as e:  # 统计永不影响路由
            logger.debug(f"[stats] record_route ignored: {e}")

    def record_event(self, kind: str, detail: dict[str, Any] | None = None) -> None:
        """杂项事件（如 reprobe_recovered）。"""
        try:
            with self._lock:
                self._events.appendleft({"t": round(time()), "kind": kind, **(detail or {})})
        except Exception as e:
            logger.debug(f"[stats] record_event ignored: {e}")

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def snapshot(self, recent_switches: int = 30, recent_events: int = 10) -> dict[str, Any]:
        """返回统计快照（自本进程启动以来的累计值）。

        - requests: 请求级计数（口径见模块 docstring）
        - legs: 每腿 attempts/successes/failures 与失败类别分布、成功均耗时
        - switches: 最近 N 条换腿事件（新→旧）
        - events: 最近 N 条杂项事件（新→旧）
        - window_seconds: 统计窗口长度（= 进程 uptime），重启清零
        """
        try:
            with self._lock:
                legs_out = {}
                for key, s in self._legs.items():
                    legs_out[key] = {
                        "attempts": s["attempts"],
                        "successes": s["successes"],
                        "failures": s["failures"],
                        "failures_by_category": dict(s["failures_by_category"]),
                        "avg_ms": round(s["ms_total"] / s["ms_count"], 1) if s["ms_count"] else None,
                    }
                return {
                    "window_seconds": round(time() - self._started_at),
                    "requests": dict(self._req),
                    "legs": legs_out,
                    "switches": list(self._switches)[:recent_switches],
                    "events": list(self._events)[:recent_events],
                }
        except Exception as e:
            logger.debug(f"[stats] snapshot ignored: {e}")
            return {"error": "stats unavailable", "detail": str(e)}


# 进程级单例（与 provider_health / model_speed 同风格）
route_stats = RouteStats()
