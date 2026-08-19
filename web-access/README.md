# web-access · AI 接入日常 Chrome 访问通道

> 类别：AI 工具接入与工程化 · 状态：已实践

## 解决什么问题

AI 助手要像真人一样上网查资料时，遇到"Chrome 通道失效 + Google 风控拦截 + 代理不分流"的连环问题。本目录记录完整排查过程与可复现的配置方案。

## 收录内容

- **[《如何在 Chrome 上发现和使用 WorkBuddy AI》](Chrome使用WorkBuddyAI实录.md)** —— 入口发现：从哪里下载、怎么上手、如何用上国外 AI 模型。
- **[《WorkBuddy-Chrome访问通道实战记录》](WorkBuddy-Chrome访问通道实战记录.md)** —— 联网通道："为什么这么做"：三层连环坑诊断、两步解决方案、社区方案对比与踩坑证据链。
- **[《Clash分流配置指南》](Clash分流配置指南.md)** —— 配置指南："怎么做"：从安装、导入订阅到规则分流配置的可复现步骤。
- **[《海外云平台作品集上线记》](海外云平台作品集上线记.md)** —— 上线复盘：把作品集仓库部署到 EdgeOne Pages 免备案上线的完整过程。

> 四篇组成「发现入口 → 联网通道 → 配置指南 → 上线复盘」的完整链路；上云实践见 [web-research/free-cloud-server](../web-research/free-cloud-server/README.md)。