# 主公的粮仓 / Zhugong's Granary

> 把 AI 接入真实工作流，做成可以运行、可以验证的自动化项目。

[English → README.md](README.md)

聚焦 **AI 应用、智能体协作与自动化实践**，同时具备轻量 Web 开发和部署能力。这里不是项目数量清单，而是一组围绕真实问题、公开证据和复盘过程整理的个人作品。

[在线作品集（Cloudflare Pages）](https://zhugong-portfolio.pages.dev/) · [GitHub 主页](https://github.com/junjiemi23-ship-it) · [邮件联系](mailto:junjiemi23@gmail.com)

## Featured / 代表作品

| 项目 | 解决的问题 | 我的角色与公开证据 | 状态 |
|---|---|---|---|
| [chat2api-sft-toolkit](chat2api-sft-toolkit/) | 每月 Chat 订阅额度用不完，而 SFT 数据标注很贵 | 围绕开源 chat2api 做了批量问答生成与数据清洗脚本（纯标准库）；基于实测沉淀逆向接线踩坑记录；双语文档 | 已实践 |
| [agent-dispatch-kit](agent-dispatch-kit/) | 多个 AI 智能体之间没有统一的派发、跟踪与验收方式 | 设计三层架构与结构化调度/汇报提示词模板；派发→跟踪→验收→建议工作流，配独立第二模型打分 | 已实践 |

多个案例均在首页直接展示“问题—角色—流程—验证”。项目目录继续承载完整代码、方法、限制和公开证据。

## 能力矩阵

| 能力 | 已实践证据 |
|---|---|
| AI 应用与自动化 | Python 状态监控、SMTP 通知、cron 定时巡检、状态机与翻转判重 |
| 智能体协作 | 写入声明、角色分工、交接文件、人工审阅门与发布前核验 |
| 设备与浏览器工作流 | ADB / scrcpy 手机操控链路、Chrome 接入、代理规则分流与故障定位 |
| 轻量 Web 交付 | 纯 HTML / CSS / JavaScript、响应式与双语页面、Cloudflare Pages 与 GitHub Pages |
| 调研与文档 | 公开信息核验、决策链记录、隐私脱敏、可复查的实战文档 |

## 仓库索引

```text
zhugong-portfolio/
├── index.html             # 双语静态作品集首页
├── assets/                # 网站分享图等公开资产
├── chat2api-sft-toolkit/  # Chat 额度变 SFT 数据集（双语）
└── agent-dispatch-kit/    # 一个入口调度所有智能体（双语）
```

## 真实性与 AI 协作说明

- 我负责提出真实需求、选择路线、设置公开与风险边界，并对最终结果进行人工验收。
- Codex、Work1、Work2 等 AI 工具参与调研、方案讨论、代码或文档起草、排错和交叉复核；项目不会把 AI 辅助内容表述成完全独立手写。
- 只有已经运行、测试或形成公开证据的内容才标记为“已实践”；计划与实验不会包装成已完成成果。
- 数字和状态优先以代码、自测入口、仓库文件或部署结果为依据；无法公开核实的内容改用定性描述。

## 隐私与合规

- 公开内容不包含真实姓名、学校、专业、年级、手机号、住址、证件、学号、服务器 IP、设备标识、密钥或授权码。
- 涉及登录态、真实业务或第三方平台的项目只公开方法论、占位配置与脱敏示例，不提交原始数据或可直接操作真实业务的脚本。
- 自动化仅用于低风险辅助并遵守相关平台条款；交易核心、发消息和其他高风险动作保留人工确认。

## 运行与联系

本站无需构建工具，直接打开 `index.html` 即可本地查看。线上主入口为 [zhugong-portfolio.pages.dev](https://zhugong-portfolio.pages.dev/)。

正在寻找 **AI 应用、智能体自动化方向实习**，也愿意承担轻量 Web 开发与部署工作：<junjiemi23@gmail.com>
