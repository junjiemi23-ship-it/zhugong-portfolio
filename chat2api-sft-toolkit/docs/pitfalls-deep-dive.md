# 逆向 API 接线的四道坑：别被"换个 base_url 就行"骗了

> 仅供研究学习、个人开发和自己使用。逆向接口可能违反服务条款，有封号风险，请勿用于公开服务或商业用途。

上一篇讲了 chat2api 怎么把订阅额度变成 OpenAI 兼容的 API。很多人第一反应是："不就是换个 base_url 吗，有什么难的？"

真上手接线——把这类通道接进你自己的客户端、训练管线——你会发现有四道坎。以及一个更大的坑，先说在前面，免得你浪费一下午。

## 坑 0：别指望它做 tool_calls

2026-09-14，我对一个自建的网页端号池中转（类型同 chatgpt2api 系）做过实测：带 `tools` 参数发请求，返回里**一次都没有出现过原生 `tool_calls`**。更离谱的是，有一次模型**以纯文本编造了一个"执行结果"**——看起来像调了工具，其实什么都没发生。

后来搞明白机制：网页后端根本不支持 `tools`，网关层收到请求后**直接把 `tools` 参数丢了**，还往上游注入了一条"不能执行工具"的系统提示。模型从头到尾不知道工具有存在过，只能靠编。

**判据**（你自己就能验）：带 `tools` 发一次真实请求，看返回的 `tool_calls` 是否非空；再看服务的 `/openapi.json` 里 `tools` 字段是不是真实声明的。有一个是假的，就别在这条路上做 agent。

**结论**：逆向通道适合生成、评测、造数据；要做 agent 工具调用，走官方 API。下面四道坎，讲的都是"只做文本生成"这个前提下的接线问题。

## 第一道坎：配置的真实来源——你改的，可能不是它读的

现象很典型：照着文档（或照着感觉）改配置，改完重启，行为纹丝不动。你开始怀疑缓存、怀疑 docker，最后发现——**它读的根本不是你改的那个地方**。

这类项目的配置来源通常有四五层：环境变量、配置文件、面板设置、命令行参数、代码里的硬编码默认值。层与层之间还有覆盖关系，比如 docker-compose 里写死的环境变量，会盖掉你精心准备的配置文件。

### 怎么过

原则只有一条：**以实际生效的为准，不以文档为准，更不以你的猜测为准**。

1. 启动时把"最终生效的配置"打印出来。有 debug/verbose 模式就开，没有就自己加两行日志。
2. 一次只改一个变量，改完看行为变没变——二分法定位到底哪一层在生效。
3. 网页端相关的参数（真实请求长什么样），**以浏览器抓包为准**。网页端的真实请求参数藏在页面 JS 里，文档是人写的，抓包是机器发的，信机器。

## 第二道坎：SSE vs JSON——流式不是"分段的 JSON"

网页端走的是流式，OpenAI 兼容层要同时应付两种形态：`stream=true` 走 SSE，`stream=false` 走一次性 JSON。混用必踩坑。

SSE 长这样（`data:` 开头，空行分隔，结束是 `data: [DONE]`）：

```
data: {"id":"chatcmpl-xxx","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","choices":[{"index":0,"delta":{"content":"你"},"finish_reason":null}]}

...

data: [DONE]
```

新手最常见的三种死法：

1. **拿 JSON 解析器直接解析整个流**——第一个 `data:` 行就炸，或者把 `[DONE]` 当 JSON 解析。
2. **忽略 `event:` 字段和注释行**——有些网关会发 `: ping` 保活注释，按 data 解析就错。
3. **非流式和流式用同一套解析**——`stream=false` 返回的是完整 `message` 对象，没有 `delta` 字段，复用流式解析逻辑直接取空。

### 怎么过

先分流：看 `Content-Type`。`text/event-stream` 就按 SSE 逐行处理，遇到 `[DONE]` 收尾；`application/json` 就整体解析。不要写"一套代码兼容两种"，那是给自己埋雷。

一个最小可用的 Python 流式读取骨架：

```python
import requests, json

r = requests.post(url, json={"model": "...", "messages": [...], "stream": True}, stream=True)
buf = ""
for line in r.iter_lines(decode_unicode=True):
    if not line or line.startswith(":"):
        continue                      # 空行、保活注释，跳过
    if line.startswith("data:"):
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        delta = chunk["choices"][0]["delta"]
        buf += delta.get("content", "")  # 追加，不是覆盖
```

空行跳过、`:` 注释跳过、`[DONE]` 判断、增量追加——这四行缺一不可。

## 第三道坎：delta 语义——吐出来的是"增量"，不是"消息"

四道坎里最阴的一道，因为**不报错，只出乱码**。

OpenAI 流式的核心约定：每个 chunk 里的是 `delta`（增量），不是完整消息：

- `role` 通常只出现在**第一个** chunk，后面全是 `content` 碎片，要自己拼。
- `finish_reason` 为 null，直到最后一个 chunk 才有值。
- `tool_calls`（官方 API 场景）按 `index` 增量拼接：`function.arguments` 是被切成十几段的字符串碎片，按 index 分组拼完**再**做 JSON 解析，提前解析必炸。

典型翻车现场：

```python
# 错误示范：把每个 chunk 当完整消息覆盖
text = ""
for chunk in stream:
    text = chunk["choices"][0]["delta"].get("content", "")  # 最后只剩最后一个字
```

更隐蔽的：

```python
# 错误示范：假设 role 每个 chunk 都有
role = chunk["choices"][0]["delta"]["role"]  # 第二个 chunk 直接 KeyError
```

### 怎么过

- `content` 永远追加：用 `+=`，用 `.get("content", "")` 防 KeyError。
- `role` 只取第一个 chunk 的，没有就默认 `"assistant"`。
- 遇到 `finish_reason` 非空就收尾，别死等 `[DONE]`（有的网关不发 `[DONE]`，直接断流）。
- 调试时把前三个 chunk 的原始 JSON 打印出来看一眼，90% 的拼接 bug 在这一步现形。

## 第四道坎：严格的 schema 校验——网页端返回的字段，客户端不认

SSE 解析对了、delta 拼对了，还有一关：**字段对不上**。

OpenAI 的客户端（官方 SDK、LangChain、各种 agent 框架）是按严格 schema 解析返回的。网页端原始返回的字段名、嵌套结构跟 OpenAI 格式不一样，网关的"翻译层"必须做一次清洗/映射。漏一个字段，客户端就抛异常——比如 `choices[0].message` 里少了 `role`，或者多了一个网页端特有的字段触发严格模式校验失败。

请求方向也一样：你按 OpenAI 格式发 `tools`、`response_format`、`strict: true`，网关要么**静默丢弃**（坑 0 就是这么来的），要么直接报错。最坑的是静默丢弃——请求 200 OK，返回看起来正常，但你的关键参数根本没生效，排错能排到怀疑人生。

### 怎么过

1. **先裸调**：用 curl 发最简请求，确认 200 和字段齐全，再一层层往客户端里套。一次引入 SDK + 网关 + 代理，出问题根本定位不到。
2. **看网关实际转发的请求**：确认它到底把你的关键参数发给上游没有。没发就是被丢了，换思路。
3. **别在逆向通道上用 `strict` / `json_schema`**：结构化输出依赖 schema 校验，逆向层的映射保真度不够，翻车率极高。真要结构化输出，自己在外面做一层解析 + 重试。

## 自检清单（接线前过一遍）

- [ ] 配置：打印最终生效配置，确认改的是它读的地方
- [ ] 抓包：网页端真实请求长什么样，以 devtools 为准
- [ ] 分流：SSE 和 JSON 两套解析，`[DONE]` 和注释行都处理
- [ ] 拼接：delta 用 `+=` 追加，role 只取首包，打印前三个 chunk 裸看
- [ ] 字段：curl 裸调先行，确认网关没丢你的关键参数
- [ ] 边界：`tools` / `strict` / `response_format` 在逆向通道上默认不可用，先验证再依赖

## 结语

这四道坎过完，逆向通道在"文本生成、评测、造数据"这个范围内就是可用的——批量生成问答对、攒 SFT 数据集，正好落在这个范围内。这也是我把它和 SFT 蒸馏链路放在一起讲的原因。

配套的批量问答生成 + 数据清洗脚本，我整理成了开源小项目：github.com/junjiemi23-ship-it/zhugong-portfolio（目录 chat2api-sft-toolkit），觉得有用点个 star。

还是那句话：仅供研究学习、个人开发和自己使用。逆向接口违反 ToS，封号是真实风险，别对外提供服务，别商用。

---

**素材来源**：坑 0 实测（2026-09-14，自建网页端号池中转，无原生 tool_calls、模型编造执行结果）与判据方法；`tools` 参数被丢弃并注入"不能执行工具"提示的机制分析；接线四道坎（真实配置来源、SSE vs JSON、增量语义、严格 schema 校验）来自逆向 API 接线实战复盘。SSE / delta  wire 格式细节以 OpenAI 官方流式接口为准。
