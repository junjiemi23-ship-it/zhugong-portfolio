# agent-dispatch-kit · 一个入口，调度所有 agent

> 配套 X 帖子："它解决了我 99% 在外面用不了电脑的问题"
> 帖子链接：https://x.com/jiemi232/status/2102741959148445825?s=46
>
> 技术篇配套帖子："一个入口调度所有 agent——Muse 当总指挥，Jev 当验收官，Bridge 当执行层"
> 帖子链接：https://x.com/jiemi232/status/2103153535206797342?s=46
>
> 懒人篇配套帖子："一段话术复制粘贴，agent 替你配好整个项目"
> 帖子链接：https://x.com/jiemi232/status/2103163429951594855?s=46
>
> 雷达篇配套帖子："把 Muse 调成你的信息雷达"
> 帖子链接：https://x.com/jiemi232/status/2103303978369134749?s=46

[English → README.md](README.md)

## 这是什么

一套方法论工具包，回答一个很具体的问题：**与其给每个 AI agent 装一个 App，不如只留一个入口——一个真正懂你意图的云端助手，让它去调度你自己电脑上的各个 agent。**

你在外面用手机说一句话，助手拆成任务、选合适的干活 agent、定验收标准、跟踪执行、验收结果（拉第二个模型独立打分），最后向你汇报。闭环四步：**派发→跟踪→验收→建议**。

这里的每一样东西都来自每天真实在跑的配置，没有纸上谈兵。

## 包含什么

- [docs/architecture.md](docs/architecture.md) —— 三层架构与设计原则（英文）
- [docs/quickstart.zh-CN.md](docs/quickstart.zh-CN.md) —— 能跑起来的最小保守配置（[English](docs/quickstart.md)）
- [docs/operations.zh-CN.md](docs/operations.zh-CN.md) —— 真实运维经验：重启纪律、超时设置、白名单工作流（[English](docs/operations.md)）
- [prompts/dispatch-template.md](prompts/dispatch-template.md) —— 给干活 agent 的结构化指令模板：目标 / 约束 / 验收标准
- [prompts/report-template.md](prompts/report-template.md) —— 干活 agent 的结构化汇报模板：完成 / 证据 / 风险
- [prompts/acceptance.md](prompts/acceptance.md) —— 验收工作流，含第二个模型独立打分
- [prompts/radar-template.zh-CN.md](prompts/radar-template.zh-CN.md) —— 把任何助手调成主动信息雷达：监控范围、优先级分层、打扰纪律（[English](prompts/radar-template.md)）
- [scripts/jev-score-example.py](scripts/jev-score-example.py) —— 独立打分的脱敏示例（API key 走环境变量，只用标准库）

## 它不是什么

- **不是远程控制工具。** 这个包里没有任何服务端代码、隧道、凭证。我自己那套控制通道是私有基础设施，出于安全原因不会公开。
- **它本身不负责"打破锁定"**——反过来：因为编排层和执行层解耦，哪家 agent 更便宜、更快、更强就换哪家，你的习惯和助手的记忆都不变。

## 适合谁

- 在自己电脑上跑多个 AI 编程 agent（opencode / codex / 各种 CLI）的人
- 经常不在电脑前、希望任务照常推进的人
- 想要真正的验收关，而不是"agent 说做完了就行"的人

## 安全说明

- 模板里只用 `[占位符]`，永远不要把 token、API key、IP、个人路径填进去。
- 打分示例脚本从 `DISPATCH_SCORER_API_KEY` 环境变量读 key，没设置就拒绝运行。

## 路线图

- 私有控制通道能否通用化、安全地开源，还在评估中。今天这个仓库里没有，将来安全设计过关之前也不会有。方法论部分可以配你信任的任何通道使用。
