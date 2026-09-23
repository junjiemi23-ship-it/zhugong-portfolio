# 把吃灰的 Chat 订阅额度，变成你的免费 API（长文版）

> 特别声明：以下内容**仅供研究学习、个人开发和自己使用**。逆向接口可能违反服务条款、存在封号风险，请勿用于公开服务或商业用途，后果自负。

## 一、两笔账并成一笔

你的 ChatGPT Plus 订阅，每个月额度用得完吗？网页端聊几句就扔那儿了，另一边写脚本调 API 还得按 token 付费。这两笔账其实能并成一笔：把网页端的订阅额度，包成 OpenAI 兼容的 API，自己写脚本调用。

## 二、实现它的开源项目：chat2api

GitHub 上的开源项目 [Sun9220/chat2api](https://github.com/Sun9220/chat2api)（MIT 协议）。一句话介绍：把网页版 ChatGPT 逆向成 OpenAI 格式的 API。请求走 `/v1/chat/completions`，返回格式和官方 API 一模一样，几乎所有支持 OpenAI 的客户端都能直接接，换个 `base_url` 就行。

## 三、原理：做一层"翻译"

它在你和 chatgpt.com 网页后端之间做了一层"翻译"：你按 OpenAI 格式发请求 → 它转成网页端的内部对话请求 → 再把网页回复翻回 API 格式（支持流式 SSE）。等于把"聊天额度"变成了"可编程的额度"。

## 四、它能干嘛

- 免登录直接用 GPT-3.5，零配置开箱
- 登录自己的账号 token 后，用 GPT-4/4o/mini、o1/o3 系列、GPTs，走的都是你订阅里本来就有的额度
- 写脚本批量对话、定时任务、接到自己的工具链——额度不再只能人肉聊天

## 五、优势（照 README 说的）

- 多账号轮询：一个 token 挂了自动换下一个重试
- RefreshToken 定时自动刷新 AccessToken，不用隔几天手动续
- 支持 Team Plus 账号、图片/文件上传（URL 和 base64 都行）、o1/o3 推理过程输出
- 可当网关多机部署

## 六、怎么用：部署

按 README 来，三选一：

- 最省事：Zeabur 一键部署
- 有服务器：`docker run -d -p 5005:5005 lanqian528/chat2api:latest`
- 本地：`pip install -r requirements.txt` 然后 `python app.py`

Plus 用户推荐用仓库里的 `docker-compose-warp.yml`。

## 七、怎么用：给它 token

浏览器登录 chatgpt.com 后，打开 `chatgpt.com/api/auth/session`，复制 accessToken 的值。然后打开服务的 `/tokens` 页面上传；或者配环境变量 `AUTHORIZATION` 设个自己的授权码，请求时当 API Key 传，自动多账号轮询。

## 八、怎么用：当 OpenAI 的 API 调

```http
POST http://127.0.0.1:5005/v1/chat/completions
Authorization: Bearer 你的token
```

body 里 model 名带 `gpt-4` 就走 GPT-4 系列（要 AccessToken），不带默认走 GPT-3.5（免登录也行）。

## 九、关键环境变量（README 原话，不懂别乱设）

- `API_PREFIX`：给接口加前缀密码，不设等于裸奔
- `PROXY_URL`：报 401/403 时配代理换出口 IP
- `ENABLE_LIMIT=true`：不去硬破官方限流，尽可能防封号
- `RANDOM_TOKEN`：多账号随机还是顺序轮询

想开官网镜像（`/login` 网页版）就开 `ENABLE_GATEWAY`，但开了等于把入口暴露出去，自己掂量。

## 十、SFT：这套玩法的真正价值

SFT——监督微调（Supervised Fine-Tuning）。一句话：给预训练好的基座模型喂"问题→标准答案"的数据对，让它学会按你想要的格式和风格回答。训练时 loss 只算在"答案"部分，问题只是条件。指令微调（instruction tuning）本身就是 SFT 的一种。

## 十一、chat2api 和 SFT 的关系：蒸馏

大模型当老师 → 用 chat2api 批量生成高质量问答对 → 攒成指令数据集 → 拿去微调本地小模型（Qwen/LLaMA 系）。学生学的是老师的回答模式。这就是个人开发者玩得起的模型定制：数据成本约等于你本来就交着的订阅费。

记住一句：SFT 学的是"模仿"，数据质量决定上限——500 条干净的比 5000 条脏的好用。

本仓库的 `scripts/` 就是干这个的：`generate_dataset.py` 批量生成问答对（断点续跑、失败重试），`clean_dataset.py` 清洗成 SFT 可用数据（去重、长度过滤、去样板回复）。

## 十二、硬提醒：tool_calls 别指望它

我自己实测过一个同类中转（网页端号池，类型同 chatgpt2api 系），有个硬提醒：这类逆向通道对 `tools` 参数支持有限——我实测没有产生原生 `tool_calls`，模型甚至以纯文本编造过执行结果。

判据：带 `tools` 发一次请求，看返回的 `tool_calls` 是否非空。所以它适合生成、评测、造数据；要做 agent 工具调用，该走官方 API 还是走官方 API。完整踩坑记录见 [pitfalls.md](pitfalls.md)。

## 十三、最后三句

1. 逆向接口违反 ToS，封号是真实风险——仅供研究学习、个人开发和自己使用，别对外提供服务，别商用。
2. 401 多半是 IP 问题（免登录对 IP 敏感，美国 IP 成功率高），429 是被限流，等一小时或换 IP。
3. 额度别浪费：chat2api 把它变成可编程的 API，SFT 把它变成你自己的小模型。下一篇讲接线时踩过的四个坑（SSE、流式增量、schema 校验）。

---

*项目信息来自 Sun9220/chat2api 仓库 README（2026-09-23 现场核验）。SFT 相关概念来自公开资料。*
