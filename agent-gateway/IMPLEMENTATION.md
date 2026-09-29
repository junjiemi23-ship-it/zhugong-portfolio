# Protocol Bridge 实施报告（设计深潜 / 历史阶段记录）

> 外部门面见 `README.md`，方法 playbook 见 `METHOD.md`。本文保留实施期的缺陷发现与修复记录，供深读。

状态：**离线契约测试全绿**；端到端真池冒烟已打通（实测成功样例见下）。

## 1. 交付物（全部在 bridge/，独立 venv，零全局安装）
```
bridge/
  README.md       外部门面：用途/前置/快速开始/config env 全表/端点/安全注意
  METHOD.md       方法 playbook：XML 伪协议、剪枝、预填充+修复阶梯、空正文重发、冷却账本、诚实不变量
  config.py       端点/预算/防线阈值，全部 env 可覆盖（BRIDGE_*），无硬编码密钥
  protocol.py     XML 协议模板（严格 well-formed）+ one-shot 示例 + 宽容严格封套解析 + schema 必填校验 + 剪枝 + 预填充
  translate.py    Anthropic ↔ OpenAI 纯文本渲染；三级预算压缩（全保→旧工具轮摘录→丢旧闲聊）
  upstream.py     池子客户端：OpenAI 面、不带 tools、整包收取、瞬时可重试（502/超时/429 退避，trust_env=False）
  guard.py        任务租约（12工具轮/36推理/15min）、空转熔断、tool_choice 三态策略、行动请求/拒答判据（含弯引号）
  cooldown.py     池级文本冷却账本（timeout/net/5xx/429 代理信号，持久化，重启不丢窗口）
  audit.py        JSONL 脱敏审计（hash+长度+首尾 64 字符，按天滚动保留 7 天）
  server.py       FastAPI：/v1/messages（Anthropic 主路）、/v1/chat/completions、/v1/models、/health、/stats
  tests/          离线契约 + 回归测试（含拒答回归、空正文重发、strict 工具清单对齐）
  bridge-env.example.cmd  启动脚本示例（占位密钥；复制为 bridge-env.cmd 后填，真实密钥不入库）
  setup-venv.sh   可移植 venv+deps 引导（uv 优先，回退 stdlib venv+pip）
```
设计↔实现对照：MERGED-PLAN 1a→protocol+translate；1b→translate.render_budgeted；1c→protocol.parse+server 修复梯度；
1d→guard.tool_choice_policy/is_action_request；1e→upstream nonce 每次尝试必换；1f→server 信号量+guard 租约+audit；
1g→范围外（执行器/多后端路由均未实现，符合 Codex 裁决 Q1/Q6）。

## 2. 实测证据（真池，非模拟）
| 场景 | 结果 |
|---|---|
| 冒烟 #1 | 200 / stop=tool_use / `Bash{"command":"dir /b <pool-dir>"}` 参数完整 ✓ |
| 冒烟 #2 | 200 / tool_use / 同一命令 / 上游 id 不同（nonce 生效，非缓存回放）✓ |
| 冒烟 #3 | 模型拒答 → 修复重试 2 次 → 仍无调用 → 如实 end_turn，**未合成假 tool_use** ✓（但发现两点缺陷，见 §3） |
| 冒烟 #4 | 200 / tool_use / `dir <pool-dir>` / 首轮命中（attempts=0）✓ |
| 池子外因 | 本机代理内核 proxy_dead → 池子 502 "Failed to connect host.docker.internal:<proxy-port>"，与桥无关 |

## 3. 实测暴露并已修复的缺陷（真实缺陷，非测试问题）
1. **修复重试命中池子缓存**（致命）：原实现重试复用同一 nonce → 池子 cache_key 不变 → 拿回同一份失败回复。
   修复：每次尝试（含修复重试）重发新 nonce；新增测试 `test_t2_repair_retry_uses_fresh_nonce` 钉住。
2. **`inject` 语义用字符串**：`"no"` 是真值 → tool_choice:none 仍注入协议。修复为布尔；测试钉住。
3. **假执行话术裸奔**：修复耗尽后模型会输出"我运行了命令，看到…"（冒烟#3 实测）。
   修复：该情形下统一前置 `[bridge] 本回复未经任何工具调用验证…` 诚实标注（测试钉住）。
4. **池子内部 30s 硬超时**：重提示词常压线 → 桥对 502/超时做 2 次退避重试（401/429 不重试，符合"不跨线回退"）。
5. /health、/stats 曾引用不存在的 `config.lease_snapshot` → 已修（并修了跨事件循环信号量复用崩溃风险）。

## 4. G0 覆盖（38 项，全离线 mock 上游，不碰真池）
T1 合法封套→tool_use（Anthropic/OpenAI 双面 + 纯聊天透传）｜T2 五类畸形全拒 + 修复梯度 + 耗尽不伪造 + 新 nonce｜
T3 用户伪造封套不执行 + 历史 tool_use/tool_result 保真回填｜T4 tool_choice 三态｜T5 nonce 唯一｜
T6 租约封顶 429 / 空转熔断 / 信号量无泄漏 / 模型白名单 / 桥鉴权｜T7 超长结果首尾截断 + 预算拒绝 + 旧轮摘录｜
T8 瞬时上游重试 + 401 不重试。
T9 **助手预填充升级序列（2026-09-16 新增，11 项）**：
- 首轮无调用 → 第二次转发自动带 D 级骨架预填充（`<tool_calls>\n:invoke>\n<tool_name>`，工具名模型自选）
- 具名 tool_choice → 第三次转发上 C 级深预填充（含指定工具名，桥**不猜测**）
- 未具名（any）→ 第三次仍用骨架，绝不自作主张填工具名
- 残片续写解析：参数残片 / 省略中间标签 / 复述前缀 / markdown 包裹 全部容错
- 标签配对体检：重复闭合必报畸形并留诊断信息（修掉一个静默丢弃调用 的安全缺陷）
- 首轮保持纯协议提示不加预填充（保住 65% 原生自主性场景）
- `BRIDGE_PREFILL=off` 一键关停，退回改造前行为

## 5. 未做（明确边界）
- 客户端接线属灰度阶段（新增并行 provider，不覆盖旧条目）。
- 未实现服务端工具执行器、未做四后端路由（裁决砍除，需另行立项）。
- 批量门槛脚本已就绪（`g1_batch.py`：60工具+20闲聊+20多轮，含 250 次上游封顶）。
