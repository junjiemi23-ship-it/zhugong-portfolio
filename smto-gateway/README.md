# smto-gateway: 三智能体共用的任务感知模型路由网关

> 让 Hermes / opencode / harness **共用一套路由、共享观测、统一免费优先、自动容错**——零配置接入，只需两个环境变量。

---

## 解决什么问题

| 痛点 | 以前 | 现在 |
|------|------|------|
| **多智能体重复配模型** | 每个都要单独写 provider、model、fallback | 一套网关，三家全用 |
| **免费模型怎么选** | 手写优先级、轮询、换腿 | 按任务类型自动选，EMA 测速 + 指数退避 |
| **限流/超时/5xx 卡住** | 请求直接失败 | 秒级自动换腿，健康检查 + 复探恢复 |
| **不知道刚才走了哪条腿** | 翻日志、grep | `curl http://127.0.0.1:8124/stats` 一行中文看懂 |
| **想强制用某模型** | 改代码、改配置、重启 | 请求头 / 环境变量 / API 强制，无需重启 |

---

## 30 秒跑通

```bash
# 1. 克隆（已在总仓里，直接用）
cd smto-gateway

# 2. 一键安装依赖（需 Python 3.11+、uv）
./scripts/install_router.sh
# 或手动：uv venv .venv && .venv/Scripts/pip install fastapi httpx uvicorn pyyaml watchfiles python-dotenv

# 3. 设置你的免费 API Key（去对应官网注册，都有免费额度）
export BAI_API_KEY="你的 b.ai key"
export NVIDIA_API_KEY="你的 NVIDIA key"
# 可选：export GROQ_API_KEY="你的 Groq key"

# 4. 启动网关（后台常驻 8124，避开 Hermes 8123）
python -m router.harness_router
# Windows 一键：powershell -ExecutionPolicy Bypass -File scripts\harness_router.ps1 start

# 5. 验证
curl http://127.0.0.1:8124/health
curl http://127.0.0.1:8124/stats     # 中文文本；加 ?format=json 拿原始数据
python -m tests.test_router          # 66 项测试全绿 = 交付通过
```

---

## 接入三大智能体

| 智能体 | 配置方式 |
|--------|---------|
| **Hermes** | 主 provider 设为 `router`（已默认走 8124）或显式 `base_url: http://127.0.0.1:8124/v1, model: auto` |
| **opencode** | `opencode.json` → `provider: smto, model: smto/auto`（已内置） |
| **harness** | 启动 `browser_harness daemon` 自动读 8124（零 LLM 纯执行器） |

> **核心原则**：模型名全写 `auto`，任务类型由网关识别，你不用记 29 个模型名字。

---

## 一行看懂的统计（新功能）

```bash
curl http://127.0.0.1:8124/stats
```

输出样例（中文、最差腿排最上、英文类别已翻译）：

```
路由统计 — 启动以来 3600s
  12 次请求 | 首腿成功 7 次 | 换腿后成功 4 次 | 全链耗尽 1 次

▸ 每腿统计
    nvidia/moonshotai/kimi-k3    尝试 5 次 | 成功 2 次 | 失败 3 次 (限流429=2, 超时=1) | 均耗时 2700ms
    bai/deepseek-v4-flash        尝试 4 次 | 成功 4 次 | 均耗时 13200ms

▸ 最近 2 次换腿（新→旧）
    16:46:55  nvidia/moonshotai/kimi-k3 → bai/deepseek-v4-flash  [限流429]
    16:45:00  nvidia/deepseek-ai/deepseek-v4-pro-0813 → bai/glm-5.3-flash  [超时]
```

> 原始数据：`?format=json` 给脚本用；默认文本给人看。

---

## 任务类型 → 候选链（自动）

| 任务类型 | 触发信号 | 首选 → 后备 |
|----------|----------|-------------|
| **vision** | 截图/图片/chart 请求 | DeepSeek V4 Flash Vision → MiniMax M3 |
| **long_running** | 工具轮数 ≥8 或上下文 >25k | Nemotron Ultra → GLM 5.3 Flash → Qwen3.8 → MiniMax M3 |
| **chinese_content** | 中文占比 >15% 且非代码 | GLM 5.3 Flash → V4 Pro 0813 → V4 Flash 0731 → Nemotron Ultra |
| **coding** | 代码/算法/调试关键词 | Nemotron Ultra → DS V4 Pro 0813 → MiniMax M3 → DS V4 Flash |
| **complex_extraction** | extract/js/schema/表格 | DeepSeek V4 Flash → DS V4 Flash 0731 → GLM → Nemotron Ultra |
| **fast_worker** | quick/simple/单步 | Qwen3.8 Flash → GLM → MiniMax M3 → gpt-oss-120b |
| **navigation_basic** | goto/click/type/简单提取 | Qwen3.8 Flash → GLM 5.3 Flash → Nemotron Ultra → MiniMax M3 |

> 优先级：vision > long_running > chinese_content > coding > complex_extraction > fast_worker > navigation_basic  
> 上下文门控：预估 token × 1.2 超过模型上限 → 自动跳过该模型

---

## 强制指定（无需重启）

```python
# 单次请求强制
client.chat.completions.create(
    model="auto",
    messages=[...],
    metadata={"force_provider": "bai", "force_model": "glm-5.3-flash"}
)
```

```bash
# 全局强制（环境变量，网关热更即刻生效）
export HARNESS_FORCE_PROVIDER=bai
export HARNESS_FORCE_MODEL=glm-5.3-flash
```

---

## 红线（硬编码不可绕过）

| 红线 | 行为 |
|------|------|
| **OpenRouter** | 任何情况下直接拦截抛错，不进入调用链 |
| **DeepSeek 官方付费 API** | 仅当 `ALLOW_DEEPSEEK_PAID=1` 且用户显式授权时放行 |

---

## 运维命令（Windows）

```powershell
# 启动/停止/重启/状态/健康/测试
scripts\harness_router.ps1 start
scripts\harness_router.ps1 stop
scripts\harness_router.ps1 restart
scripts\harness_router.ps1 status
scripts\harness_router.ps1 health
scripts\harness_router.ps1 test
```

---

## 配置热更

修改 `config/harness_router.yaml` 后无需重启（`watchfiles` 自动监听）：

```yaml
port: 8124
retry:
  max_attempts_per_chain: 3
  timeout_seconds: 60
context_gate:
  safety_margin: 1.2
task_detection:
  long_running_tool_rounds: 8
  long_running_context_chars: 25000
  chinese_ratio_threshold: 0.15
```

---

## 测试验收

```bash
python -m tests.test_router   # 66 项测试全绿 = 交付通过
```

覆盖：候选链完整性、上下文门控、任务类型检测、红线拦截、环形缓冲上限、统计输出格式。

---

## 目录结构

```
smto-gateway/
├── router/                 # FastAPI 网关核心
│   ├── harness_router.py   # 入口：/health /v1/chat/completions /stats
│   ├── route_candidates.py # 任务类型→候选链 + 检测逻辑
│   ├── context_gate.py     # 上下文门控
│   ├── fallback_chain.py   # 全局 Fallback + EMA 排序
│   ├── provider_client.py  # 统一 Provider 客户端 + 红线拦截
│   ├── health.py           # 健康检查
│   └── stats.py            # 观测统计（环形缓冲 500 条，重启清零）
├── config/
│   ├── harness_router.yaml # 路由规则（热更）
│   └── providers.yaml      # Provider 端点/模型列表（用 key_env 引用环境变量）
├── scripts/
│   ├── install_router.sh   # 一键安装
│   ├── harness_router.ps1  # Windows 运维
│   ├── prep_release_check.py # 发布前安全扫描
│   └── start_detached.ps1  # 后台启动
├── tests/
│   └── test_router.py      # 66 项冒烟测试（无需真实密钥）
├── pyproject.toml
├── uv.lock
└── .gitignore
```

---

## 依赖

- Python ≥ 3.11
- `uv` 推荐管理依赖：`fastapi`, `uvicorn`, `httpx`, `watchfiles`, `python-dotenv`, `pyyaml`
- 环境变量（去官网注册免费账号）：
  - `BAI_API_KEY`  — https://b.ai
  - `NVIDIA_API_KEY` — https://build.nvidia.com
  - `GROQ_API_KEY`  — 可选，https://console.groq.com

---

## License

MIT