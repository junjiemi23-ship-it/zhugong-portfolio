"""对 harness 网关(8124)强制指定模型发真实短请求，测各链时延。
并行测量（asyncio.gather），控制单请求超时，输出耗时/状态表。"""
import asyncio, json, time, urllib.request

GATEWAY = "http://127.0.0.1:8124/v1/chat/completions"
PROBE = "请用一句话回答：1+1等于几？"

# 各任务链的候选（与 route_candidates 对齐）
MODELS = [
    ("navigation_basic/fast", "bai", "qwen3.8-flash"),
    ("chinese_content", "bai", "deepseek-v4-flash"),
    ("coding", "nvidia", "minimaxai/minimax-m3"),
    ("complex_extraction", "nvidia", "deepseek-ai/deepseek-v4-flash-0731"),
    ("vision", "bai", "deepseek-v4-flash-vision-exp"),
]

async def probe(tag, provider, model, sem):
    async with sem:
        payload = {
            "model": "auto",
            "messages": [{"role": "user", "content": PROBE}],
            "metadata": {"force_provider": provider, "force_model": model},
            "max_tokens": 30,
            "stream": False,
        }
        body = json.dumps(payload).encode()
        req = urllib.request.Request(GATEWAY, data=body, headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=35) as r:
                d = json.loads(r.read())
            dt = round(time.time() - t0, 1)
            got = d.get("model", "?")
            return f"{tag:24s} {provider:7s} {model:38s} {dt:6.1f}s  OK  -> {got}"
        except Exception as e:
            dt = round(time.time() - t0, 1)
            return f"{tag:24s} {provider:7s} {model:38s} {dt:6.1f}s  FAIL({type(e).__name__})"

async def main():
    sem = asyncio.Semaphore(3)  # 并发3，避免撞限流
    tasks = [probe(t, p, m, sem) for t, p, m in MODELS]
    for r in await asyncio.gather(*tasks):
        print(r)

asyncio.run(main())
