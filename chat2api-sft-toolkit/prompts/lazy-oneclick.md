# 懒人一键指令（复制下一节整段，发给你的 AI Agent）

> 使用说明：把下面 `---` 之间的整段复制，粘贴发给你的 agent（Cursor / opencode / codex / Claude 等）。全程它自动跑，你只需要在标记的地方露面：粘一下 token、定一下主题和数量、最后抽查确认。

---

你是一名资深 AI 工程助手。请帮我完成以下任务，全程自动化执行，只有在标记的地方停下来问我，不要让我学任何原理。

## 我的情况
- 我有 ChatGPT Plus 订阅，额度经常用不完
- 目标：把订阅额度变成 OpenAI 兼容的 API，批量生成问答对，清洗成 SFT（监督微调）数据集

## 任务步骤（按顺序做完）

### 1. 部署 chat2api
- 项目：https://github.com/Sun9220/chat2api（MIT 协议）
- 按它 README 部署（三选一：Zeabur 一键 / docker / 本地 pip），选你环境里最顺的一种
- 必须设置 API_PREFIX（别裸奔）；Plus 用户可以用仓库里的 docker-compose-warp.yml

### 2. 接入我的 token
- 停下来告诉我：去浏览器打开 https://chatgpt.com/api/auth/session，复制 accessToken 的值粘给你
- 拿到后通过服务的 /tokens 页面或环境变量配进去
- 然后用 curl 调 POST /v1/chat/completions（问一个简单问题，stream=false），确认返回 200 且有正常文本，再往下走

### 3. 批量生成问答对
- 先问我两个问题：① 生成什么主题的问答？② 要多少条？
- 然后 clone 工具包：https://github.com/junjiemi23-ship-it/zhugong-portfolio，看 chat2api-sft-toolkit 目录
- 用它的 scripts/generate_dataset.py（如果跑不起来，就按 examples/prompts_example.txt 的格式写一个等价脚本），把 base_url 指向上一步的服务，循环生成，输出到 data/raw.jsonl
- 遇到 429（限流）就等一小时再继续；遇到 401 就停下来告诉我换 IP 或代理

### 4. 清洗成 SFT 数据集
- 用 scripts/clean_dataset.py 清洗 data/raw.jsonl：去重、过滤过短和乱码，输出标准 JSONL（每行 {"prompt": "...", "completion": "..."}）到 data/sft.jsonl
- 统计并告诉我：原始多少条、清洗后剩多少条、主要过滤原因是什么

### 5. 抽查验收
- 随机抽 20 条展示给我，我确认质量没问题才算完
- 质量不行就告诉我原因（主题偏了 / 格式乱了 / 答案太水），问我要不要换主题重跑

## 红线（碰到就停下来问我，不要自作主张）
- 这套东西只给我个人研究学习用：不对外提供服务、不商用
- 任何花钱的操作、任何对外发布的操作，先问我
- 不要尝试用这个通道做 tool_calls / agent 工具调用——实测不支持，做了也白做
- 我的 accessToken 只用在这一个任务里，不要写进任何会被上传的文件

## 验收标准（全部打勾才算完）
- [] POST /v1/chat/completions 返回 200，有正常文本
- [] data/raw.jsonl 里有我指定数量的问答对
- [] data/sft.jsonl 格式正确，每行都有 prompt 和 completion
- [] 20 条抽查我已确认通过

---

*配套脚本与长文讲解：https://github.com/junjiemi23-ship-it/zhugong-portfolio（chat2api-sft-toolkit）*
*仅供研究学习、个人开发和自己使用；逆向接口有封号风险，勿商用、勿对外提供服务。*
