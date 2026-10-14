# assistant-pc-access-kit · 把你的电脑交到 AI 助手手里

> 配套 X 帖：《如何让 Muse 用上你的电脑》（发布后补链接）
>
> [English → README.md](README.md)

## 这是什么

一套实战总结：**AI 助手一旦能用你的电脑，就从"问答机器"变成了"办事的人"**——跑命令、调你的账号、从手机接指令、按定时任务在你睡觉时继续干活。

这里有四层接入架构、接入顺序、安全红线和任务指令模板。每一项都在真实日常跑着的东西，不是纸上谈兵。

## 四层接入

1. **助手自己的云电脑**——终端、浏览器、文件系统，7x24 在线。查资料、跑脚本、做文件。
2. **你连上的账号**——邮件、日历等。先给只读权限，要动手先审批。
3. **你配对的手机**——遥控器。在哪都能下指令，进度和结果回到手机上。
4. **你的 PC（私有桥接）**——电脑变成它的手。它把任务派给电脑上现成的智能体：派任务 → 跟踪 → 独立验收 → 汇报，四步闭环。

详解：[docs/architecture.md](docs/architecture.md)

## 目录

- [docs/architecture.md](docs/architecture.md)——四层架构与任务流向
- [docs/access-checklist.md](docs/access-checklist.md)——按这个顺序接入，每步有验收标准
- [docs/security.md](docs/security.md)——不可谈判的安全红线
- [docs/scheduling.md](docs/scheduling.md)——定时任务模式：一次配置，永久在线
- [prompts/task-template.md](prompts/task-template.md)——怎么给助手下指令，活才能真正干完

相关项目：[agent-dispatch-kit](../agent-dispatch-kit/)——另一半：调度电脑上智能体的方法论（派发→跟踪→验收→建议）。

## 这不是什么

- **不是远程控制软件。** 本项目不含任何服务器代码、隧道配置、凭证。我自己用的私有桥接是私有基础设施，出于安全原因不公开。
- **不是审批的捷径。** 花钱、发消息、动你账号这类敏感操作，永远先要你的明确批准。方便不能凌驾于同意。

## 安全说明

- 所有模板只用 `[占位符]`。不要把 token、API key、IP、个人路径填进去。
- 凭证只进保险库，不进聊天、不进仓库、不进日志。一旦出现在截图或聊天里，按永久泄露处理：立即撤销轮换。

## 协议

MIT——见仓库根目录 [LICENSE](../LICENSE)。本目录内容 © 2026 Junjie Mi。
