# 主公的粮仓 / Zhugong's Granary

> 把 AI 接入真实工作流，做成可以运行、可以验证的自动化项目。

聚焦 **AI 应用、智能体协作与自动化实践**，同时具备轻量 Web 开发和部署能力。这里不是项目数量清单，而是一组围绕真实问题、公开证据和复盘过程整理的个人作品。

[在线作品集（Cloudflare Pages）](https://zhugong-portfolio.pages.dev/) · [GitHub 主页](https://github.com/junjiemi23-ship-it) · [邮件联系](mailto:junjiemi23@gmail.com)

## Featured / 代表作品

| 项目 | 解决的问题 | 我的角色与公开证据 | 状态 |
|---|---|---|---|
| [codex-quota-monitor](codex-quota-monitor/) | AI 工具没有主动状态提醒，人工盯信号容易漏报或重复打扰 | 定义提醒边界与验收场景，推动状态机、翻转判重和防抖方案落地；公开零依赖 Python 脚本、配置模板和三类离线自测入口 | 已实践 |
| [phone-automation](phone-automation/) | WebView、自绘 UI 或深色模式下，常规元素树和颜色检测无法可靠定位目标 | 提供标注并验证结果，选择“人工标注 + 像素差异”路线，划定低风险自动化边界；公开方法论、伪代码和脱敏示意图 | 已实践 |
| [web-access](web-access/) | AI 在真实浏览器环境查资料时，会同时遇到登录态、Chrome 通道和代理分流问题 | 定义访问目标与验收方式，组织多智能体排错和交接，复核通道效果；公开 4 篇从入口发现到上线复盘的实战文档 | 已实践 |
| [smto-gateway](smto-gateway/) | 三智能体各自配模型、免费额度易超限、换腿靠手、排障翻日志 | 设计任务感知路由 + 观测统计 + 红线保护；公开 66 项自测、中文统计、零配置三智能体共用 | 已实践 |

三个案例均在首页直接展示“问题—角色—流程—验证”。项目目录继续承载完整代码、方法、限制和公开证据。

## 能力矩阵

| 能力 | 已实践证据 |
|---|---|
| AI 应用与自动化 | Python 状态监控、SMTP 通知、cron 定时巡检、状态机与翻转判重 |
| 智能体协作 | 写入声明、角色分工、交接文件、人工审阅门与发布前核验 |
| 设备与浏览器工作流 | ADB / scrcpy 手机操控链路、Chrome 接入、代理规则分流与故障定位 |
| 轻量 Web 交付 | 纯 HTML / CSS / JavaScript、响应式与双语页面、Cloudflare Pages 与 GitHub Pages |
| 调研与文档 | 公开信息核验、决策链记录、隐私脱敏、可复查的实战文档 |

## Practiced / 其他已实践

- [overseas-deploy](overseas-deploy/)：部署选型、Cloudflare Pages / GitHub Pages、SEO 迁移和故障复盘；本站即交付物。
- [web-research](web-research/)：公开资源检索与结构化整理；首个案例记录免费云资源甄别、领取与到期防扣费决策链。
- [docs](docs/)：多智能体共管协议与公开协作方法，记录角色边界、审阅门和风险红线。
- [二手数码套利监控实战文档](docs/articles/二手数码套利监控从零搭建实战.md)：从需求拆解到自动化管线的脱敏复盘。

## Labs / 实验与规划

这些方向尚未作为完成成果展示，状态以各目录 README 为准：

- [ai-chat](ai-chat/)：AI 助手接入与体验比较——规划。
- [surveys](surveys/)：问卷设计与结构化数据流程——规划。
- [chat-companion](chat-companion/)：只使用脱敏示例的角色化对话实验——实验。
- [holiday-pages](holiday-pages/)：方向待重新定义——待定。

## 仓库索引

```text
zhugong-portfolio/
├── index.html             # 双语静态作品集首页
├── assets/                # 网站分享图等公开资产
├── codex-quota-monitor/   # Python 状态监控与通知
├── phone-automation/      # ADB / scrcpy 与人机协作识图
├── web-access/            # Chrome 接入、分流与排错文档
├── smto-gateway/          # 三智能体共用模型路由网关
├── overseas-deploy/       # 轻量网页部署与可达性复盘
├── web-research/          # 公开资源检索与验证
├── docs/                  # 方法文档、文章与协作约定
├── ai-chat/               # Lab：AI 对话平台实验
├── surveys/               # Lab：调研与数据处理
├── chat-companion/        # Lab：脱敏角色对话
└── holiday-pages/         # Lab：待重新定义
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
