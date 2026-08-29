"""对 harness 网关(8124)发起强制指定模型的真实请求, 验证各模型在 harness 通道下的可用性."""
import json
import time
import urllib.request

GATEWAY = "http://127.0.0.1:8124/v1/chat/completions"

# 候选: 与 route_candidates.py 链中引用一致
MODELS = [
    ("bai", "glm-5.3-flash"),
    ("bai", "deepseek-v4-flash"),
    ("bai", "qwen3.8-flash"),
    ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"),
    ("nvidia", "minimaxai/minimax-m3"),
    ("nvidia", "deepseek-ai/deepseek-v4-flash-0731"),
    ("nvidia", "deepseek-ai/deepseek-v4-pro-0813"),  # 疑似失效
    ("groq", "gpt-oss-120b"),
]

def call(provider, model):
    payload = {
        "model": "auto",
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "metadata": {"force_provider": provider, "force_model": model},
        "max_tokens": 10,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(GATEWAY, data=data, headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode())
            ms = int((time.time() - start) * 1000)
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            return f"OK {ms}ms content={content!r}"
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode()
        except Exception:
            err = ""
        ms = int((time.time() - start) * 1000)
        return f"HTTP {e.code} {ms}ms {err[:120]}"
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        return f"ERR {ms}ms {type(e).__name__}: {e}"

for provider, model in MODELS:
    print(f"--- {provider}/{model} ---")
    print(call(provider, model))
    print()
