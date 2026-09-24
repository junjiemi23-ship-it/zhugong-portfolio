# chat2api-sft-toolkit · 把吃灰的 Chat 订阅额度变成 SFT 数据集

> 配套 X 帖子：《把吃灰的 Chat 订阅额度，变成你的免费 API》
> 帖子链接：https://x.com/jiemi232/status/2102592126412587502?s=46
> 配套帖子二（踩坑长文）：https://x.com/jiemi232/status/2102726759800328567?s=46

[English → README.md](README.md)

## 这是什么

一个小工具包，回答一个具体问题：**你每个月交着的 Chat 订阅额度，除了人肉聊天，还能不能变成你自己的东西？**

思路来自开源项目 [Sun9220/chat2api](https://github.com/Sun9220/chat2api)（MIT）：它把网页版 ChatGPT 逆向成 OpenAI 兼容的 API（`POST /v1/chat/completions`，本地默认 `http://127.0.0.1:5005/v1`）。额度还是你订阅里的额度，但变成了**可编程的额度**。

这个工具包做的是"后半程"：用大模型当老师，批量生成高质量问答对，清洗成干净的指令数据集，拿去微调本地小模型（Qwen / LLaMA 系）——也就是**蒸馏**。SFT 学的是"模仿"，数据质量决定上限：500 条干净的比 5000 条脏的好用。

## 适合谁

- 交着 Plus / Pro 订阅、额度用不完的个人开发者
- 想低成本玩 SFT / 蒸馏、但不想为数据标注付费的人
- 对"逆向 API 能做什么、不能做什么"有清醒认知的人（先看 [docs/pitfalls.md](docs/pitfalls.md)）

## 特别声明（先读）

**以下内容仅供研究学习、个人开发和自己使用。** 逆向接口可能违反服务条款，封号是真实风险。请勿用于公开服务或商业用途，后果自负。

另外一个硬提醒（来自实测）：这类逆向通道对 `tools` 参数支持有限——实测没有产生原生 `tool_calls`，模型甚至以纯文本编造过执行结果。所以它适合**生成、评测、造数据**；要做 agent 工具调用，请走官方 API。详见 [docs/pitfalls.md](docs/pitfalls.md)。

## 懒人一键指令

不想动手？把 [prompts/lazy-oneclick.md](prompts/lazy-oneclick.md) 里 `---` 之间的整段复制，粘贴发给你的 agent（Cursor / opencode / codex / Claude 等），它会自动跑完部署 → 接入 token → 批量生成 → 清洗成 SFT 数据集 → 抽查验收。你只需要在标记的地方露面：粘一下 token、定一下主题和数量、最后抽查确认。红线：仅个人研究学习用，不商用、不对外提供服务。

## 快速开始

你需要**自己的一套 chat2api 部署**（按 [Sun9220/chat2api](https://github.com/Sun9220/chat2api) 的 README 来，三选一）：

```bash
# 最省事：Zeabur 一键部署；有服务器：
docker run -d -p 5005:5005 lanqian528/chat2api:latest
# 本地：pip install -r requirements.txt && python app.py
```

然后：

```bash
# 1. 准备问题清单（每行一个），示例可直接改
cp examples/prompts_example.txt my_prompts.txt

# 2. 配置（全部走环境变量，也可用命令行 flag 覆盖，--help 查看）
export CHAT2API_BASE_URL=http://127.0.0.1:5005/v1
export CHAT2API_API_KEY=你的授权码        # 没设 AUTHORIZATION 就留空
export CHAT2API_MODEL=gpt-4o-mini         # 按你的部署和登录情况改

# 3. 批量生成（断点续跑：已生成过的问题会自动跳过）
python3 scripts/generate_dataset.py --prompts my_prompts.txt --out data/qa_raw.jsonl

# 4. 清洗成 SFT 可用数据（去重、长度过滤、去样板回复，并打印统计）
python3 scripts/clean_dataset.py --in data/qa_raw.jsonl --out data/qa_sft.jsonl
```

`data/` 下的 `*.jsonl` 不会进仓库（见 `.gitignore`），数据只留在你本地。

依赖：只有 Python 标准库，零第三方包。

## 目录结构

```text
chat2api-sft-toolkit/
├── README.md               # 英文版
├── README.zh-CN.md         # 本文件（中文版）
├── LICENSE                 # MIT
├── scripts/
│   ├── generate_dataset.py # 批量问答生成（断点续跑、指数退避重试）
│   └── clean_dataset.py    # SFT 数据清洗（去重、过滤、统计）
├── docs/
│   ├── pitfalls.md         # 踩坑记录：tool_calls 与逆向接线四道坎
│   ├── pitfalls-deep-dive.md # 深度长文：坑 0 + 逆向接线四道坎（中文）
│   └── article.md          # 配套帖子的长文版（中文）
├── prompts/
│   └── lazy-oneclick.md    # 懒人一键指令：复制一段话发给 agent，全自动跑完
└── examples/
    └── prompts_example.txt # 示例问题清单
```

## 相关项目

- [codex-quota-monitor](../codex-quota-monitor/) —— 盯 AI 额度/状态信号的监控脚本：状态翻转时邮件推送。本工具包只管"把额度变成数据"，额度本身的监控用它，不重复造轮子。

## 协议

MIT（见 [LICENSE](LICENSE)）。chat2api 本体是 Sun9220/chat2api（MIT），本项目是它周边的数据工具包，不含任何逆向服务端实现。
