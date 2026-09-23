# 踩坑记录：逆向通道的 tool_calls 与接线四道坎

> 本页每一条都有来源卡片，不编故事。卡片来自作者的本地知识库（zhugong-embed），结论页注出处。

## English summary

- Don't count on reverse-engineered channels for `tool_calls`: a 2026-09-14 test against a self-hosted web-account pool (same family as chatgpt2api) produced **zero native `tool_calls`**, and the model **fabricated execution results in plain text**. Source: `local-web-pool-api.md`
- Test it yourself: send one real request with `tools` and check whether the returned `tool_calls` is non-empty; also check whether the service's `/openapi.json` actually declares a `tools` field. Source: `local-web-pool-api.md`
- Why it happens: the web backend **drops the `tools` parameter** and injects a "tools cannot be executed" system prompt — the model never knows tools exist, so it improvises. Source: `agent-gateway-strategy-roadmap.md`
- Wiring a reverse-engineered web backend into "something that looks like the OpenAI API" means clearing four hurdles (source: `playbook-reverse-webapi-agent.md`): real configuration source, SSE vs JSON, delta semantics, strict schema validation.

**Bottom line**: reverse-engineered channels are for generation, evaluation, and data synthesis (exactly what this toolkit does); for agentic tool calling, use the official API.

## 坑 0（最大的）：别指望逆向通道做 tool_calls

- **实测结论**：2026-09-14，对一个自建网页端号池中转（类型同 chatgpt2api 系）实测——**没有产生原生 `tool_calls`**，模型甚至**以纯文本编造过执行结果**（看起来像调了工具，其实没有）。来源：`local-web-pool-api.md`
- **判据**：带 `tools` 参数发一次真实请求，看返回里的 `tool_calls` 是否非空；同时检查服务的 `/openapi.json` 里 `tools` 字段是否真实存在。来源：`local-web-pool-api.md`
- **机制解释**：网页后端会**丢弃 `tools` 参数**，并注入一条"不能执行工具"的系统提示——所以模型根本不知道有工具这回事，只能靠编。来源：`agent-gateway-strategy-roadmap.md`

**结论**：逆向通道适合生成、评测、造数据（正是本工具包的用途）；要做 agent 工具调用，请走官方 API。

## 接线四道坎

把逆向网页后端接成"像 OpenAI API 一样"的服务时，要过的四道坎。来源：`playbook-reverse-webapi-agent.md`

1. **真实配置来源**——网页端的真实请求参数藏在页面/JS 里，照文档猜出来的配置大概率不对，必须以实际抓到的为准。
2. **SSE vs JSON**——网页端走流式 SSE，OpenAI 兼容层要同时处理流式和非流式两种返回形态，混用必踩坑。
3. **增量语义（delta semantics）**——SSE 吐的是增量片段（delta），不是完整消息；拼接逻辑错一位，内容就全乱。
4. **严格 schema 校验**——OpenAI 格式的 schema 校验很严，网页端返回的字段稍有出入就直接报错，要做一层清洗/映射。

> 想自己搭 chat2api 一类服务的人，先把这四道坎过一遍；只想用本工具包造数据的人，看完"坑 0"就可以去跑脚本了。
