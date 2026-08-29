"""
任务类型 → 候选模型链映射表
参考 Hermes smart-model-router 表，按 harness 场景调整。

2026-08-28 修订（对照 opencode 基线 router-baseline.md）：
1. 新增 coding 任务类：纯代码/算法/调试路由到强模型（NVIDIA nemotron / deepseek-v4-pro-0813）
2. 修复关键词撞车：analyze 不再触发 vision；json 不再单独触发 complex_extraction/fast_worker
3. chinese_content 第 2 腿换 NVIDIA 免费 deepseek-v4-pro-0813（原 B.AI 付费 SKU deepseek-v4-pro 移除）
4. 移除不可用腿：local mimo-v2.5（进程未运行）；groq gpt-oss-120b（密钥待确认）降为 fast_worker 末位
"""

from dataclasses import dataclass
from typing import Literal

Provider = Literal["bai", "nvidia", "groq", "local"]
TaskType = Literal[
    "navigation_basic",      # 导航/基础交互
    "complex_extraction",    # 复杂提取/结构化
    "long_running",          # 长周期/多轮
    "vision",                # 视觉/截图分析
    "fast_worker",           # 高频短指令
    "chinese_content",       # 中文重内容
    "coding",                # 纯代码/算法/调试（强模型）
]


@dataclass(frozen=True, slots=True)
class Candidate:
    """单个候选模型

    quality_tier: 质量分层（用户理念 2026-08-29：性能强且稳定 > 性能强但不稳定 > 性能一般但稳定）
        1 = 性能顶尖且稳定（kimi-k3 独占）
        2 = 性能顶尖但慢/偶发不稳（pro-0813、nemotron 恢复后）
        3 = 性能一般但非常稳定（flash/qwen 系）
    排序 = 可用性 → quality_tier → EMA 速度（tier 是主键，速度是层内竞争键）
    """
    provider: Provider
    model: str
    display_name: str
    context_limit: int          # 最大上下文 token
    is_free: bool = True        # 是否免费
    vision_capable: bool = False  # 是否支持视觉
    quality_tier: int = 3       # 1=顶尖且稳, 2=顶尖但慢/不稳, 3=一般但稳
    notes: str = ""


# 候选模型链：按优先级排序（首选在前）
# 2026-08-29 质量分层（用户理念）：tier1 性能顶尖且稳(kimi-k3 独占) > tier2 顶尖但慢/不稳(pro-0813/nemotron) > tier3 一般但稳(flash/qwen/minimax/glm)
# 排序键 = 可用性 → tier → EMA 速度；tier2 的不稳定由 _try_chain 自动换腿兜底。
# 2026-08-29 实测复核（低负载时恢复）：
#   可用且快: bai/qwen3.8-flash(1.8s), bai/deepseek-v4-flash(1.7s), bai/glm-5.3-flash(1.9s)
#   可用但慢: nvidia/deepseek-ai/deepseek-v4-flash-0731(30s), nvidia/deepseek-ai/deepseek-v4-pro-0813(31s, 1M ctx)
#   上游 503: nvidia/nvidia/nemotron-3-ultra-550b-a55b, groq/gpt-oss-120b(缺 key)
# 注：tier 只影响质量敏感链(coding/extract/long/fallback)；短任务链(navigation/fast/vision)无 tier1/2 腿，不会被强模型拖慢
ROUTE_CANDIDATES: dict[TaskType, list[Candidate]] = {
    "navigation_basic": [
        Candidate("bai", "qwen3.8-flash", "Qwen3.8 Flash (B.AI)", 128_000, vision_capable=False),
        Candidate("bai", "deepseek-v4-flash", "DeepSeek V4 Flash (B.AI)", 128_000, vision_capable=False),
        Candidate("nvidia", "minimaxai/minimax-m3", "MiniMax M3 (NVIDIA)", 1_000_000, vision_capable=False),
        # 低负载快腿备胎(2026-08-29 加回): 实测 1.9s, 高负载限流时熔断自动跳过
        Candidate("bai", "glm-5.3-flash", "GLM 5.3 Flash (B.AI)", 128_000, vision_capable=False,
                  notes="低负载恢复, 1.9s; 高负载 429 自动冷却"),
    ],
    "coding": [
        # kimi-k3 (NVIDIA, Moonshot 旗舰): 2026-08-29 免费化后实测 2.7s, 1M 上下文, 强推理 → coding 首选
        Candidate("nvidia", "moonshotai/kimi-k3", "Kimi K3 (NVIDIA)", 1_000_000, vision_capable=False, quality_tier=1,
                  notes="2026-08-29 免费化, 实测2.7s, 1M ctx, 强推理"),
        Candidate("nvidia", "minimaxai/minimax-m3", "MiniMax M3 (NVIDIA)", 1_000_000, vision_capable=False),
        Candidate("bai", "deepseek-v4-flash", "DeepSeek V4 Flash (B.AI)", 128_000, vision_capable=False),
        # nemotron-3-ultra 上游曾 503; 加回末位由动态优先级管理——恢复后自动上位, 未恢复时沉底不碍事
        Candidate("nvidia", "nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra (NVIDIA)", 1_000_000, vision_capable=False, quality_tier=2,
                  notes="上游 503 曾失效; 动态优先级自动管理"),
        # 强推理慢腿兜底(2026-08-29 加回): 实测 31s 可用; 前腿全挂才走到
        Candidate("nvidia", "deepseek-ai/deepseek-v4-pro-0813", "DeepSeek V4 Pro 0813 (NVIDIA)", 1_000_000, vision_capable=False, quality_tier=2,
                  notes="低负载恢复, 31s; 慢但强推理兜底; 2026-08-29 实测 1M ctx"),
        # Strong-model leg: 未来 nemotron-ultra 恢复上游后可在 nvidia 下换回; 现因 503 降权
    ],
    "complex_extraction": [
        Candidate("bai", "deepseek-v4-flash", "DeepSeek V4 Flash (B.AI)", 128_000, vision_capable=False),
        Candidate("nvidia", "moonshotai/kimi-k3", "Kimi K3 (NVIDIA)", 1_000_000, vision_capable=False, quality_tier=1,
                  notes="2026-08-29 免费化, 1M ctx"),
        Candidate("nvidia", "deepseek-ai/deepseek-v4-flash-0731", "DeepSeek V4 Flash 0731 (NVIDIA)", 128_000, vision_capable=False),
        Candidate("nvidia", "minimaxai/minimax-m3", "MiniMax M3 (NVIDIA)", 1_000_000, vision_capable=False),
        # 强推理兜底(2026-08-29 加回): 慢但可用的 pro-0813
        Candidate("nvidia", "deepseek-ai/deepseek-v4-pro-0813", "DeepSeek V4 Pro 0813 (NVIDIA)", 1_000_000, vision_capable=False, quality_tier=2,
                  notes="低负载恢复, 31s; 强推理兜底; 2026-08-29 实测 1M ctx"),
    ],
    "long_running": [
        # kimi-k3 1M ctx 最适合长会话; minimax-m3 同为 1M 备用
        Candidate("nvidia", "moonshotai/kimi-k3", "Kimi K3 (NVIDIA)", 1_000_000, vision_capable=False, quality_tier=1,
                  notes="2026-08-29 免费化, 1M ctx, 实测2.7s"),
        Candidate("nvidia", "minimaxai/minimax-m3", "MiniMax M3 (NVIDIA)", 1_000_000, vision_capable=False),
        Candidate("bai", "deepseek-v4-flash", "DeepSeek V4 Flash (B.AI)", 128_000, vision_capable=False),
        Candidate("bai", "qwen3.8-flash", "Qwen3.8 Flash (B.AI)", 128_000, vision_capable=False),
        # 1M ctx 长会话兜底(2026-08-29 实测确认 pro-0813 = 1048576): 慢腿, 前腿全挂才走到
        Candidate("nvidia", "deepseek-ai/deepseek-v4-pro-0813", "DeepSeek V4 Pro 0813 (NVIDIA)", 1_000_000, vision_capable=False, quality_tier=2,
                  notes="实测 1M ctx; 慢(~31s), 长会话 1M 兜底腿"),
    ],
    "vision": [
        Candidate("bai", "deepseek-v4-flash-vision-exp", "DeepSeek V4 Flash Vision (B.AI)", 128_000, vision_capable=True),
        Candidate("nvidia", "minimaxai/minimax-m3", "MiniMax M3 (NVIDIA)", 1_000_000, vision_capable=True),
    ],
    "fast_worker": [
        Candidate("bai", "qwen3.8-flash", "Qwen3.8 Flash (B.AI)", 128_000, vision_capable=False),
        Candidate("bai", "deepseek-v4-flash", "DeepSeek V4 Flash (B.AI)", 128_000, vision_capable=False),
        Candidate("nvidia", "minimaxai/minimax-m3", "MiniMax M3 (NVIDIA)", 1_000_000, vision_capable=False),
        # 低负载快腿备胎(2026-08-29 加回)
        Candidate("bai", "glm-5.3-flash", "GLM 5.3 Flash (B.AI)", 128_000, vision_capable=False,
                  notes="低负载恢复, 1.9s; 高负载 429 自动冷却"),
    ],
    "chinese_content": [
        # kimi-k3 中文旗舰, 1M ctx → chinese 首选
        Candidate("nvidia", "moonshotai/kimi-k3", "Kimi K3 (NVIDIA)", 1_000_000, vision_capable=False, quality_tier=1,
                  notes="Moonshot 中文旗舰, 2026-08-29 免费"),
        Candidate("bai", "deepseek-v4-flash", "DeepSeek V4 Flash (B.AI)", 128_000, vision_capable=False),
        Candidate("nvidia", "minimaxai/minimax-m3", "MiniMax M3 (NVIDIA)", 1_000_000, vision_capable=False),
        Candidate("nvidia", "deepseek-ai/deepseek-v4-flash-0731", "DeepSeek V4 Flash 0731 (NVIDIA)", 128_000, vision_capable=False),
    ],
}

# 全局 Fallback 链（仅任务类型未命中时使用；免费优先、付费殿后——付费不进链，由红线兜底）
# 2026-08-29 更新: 加入 kimi-k3 (免费化); 移除失效的 glm(45s 限流)/nemotron(503)/pro-0813(超时)
GLOBAL_FALLBACK: list[Candidate] = [
    Candidate("nvidia", "moonshotai/kimi-k3", "Kimi K3 (NVIDIA)", 1_000_000, quality_tier=1, notes="2026-08-29 免费化"),
    Candidate("bai", "deepseek-v4-flash", "DeepSeek V4 Flash (B.AI)", 128_000),
    Candidate("nvidia", "minimaxai/minimax-m3", "MiniMax M3 (NVIDIA)", 1_000_000),
    Candidate("bai", "qwen3.8-flash", "Qwen3.8 Flash (B.AI)", 128_000),
    Candidate("nvidia", "deepseek-ai/deepseek-v4-flash-0731", "DeepSeek V4 Flash 0731 (NVIDIA)", 128_000),
    # 末位恢复腿(2026-08-29 加回): 低负载可用, 限流自动熔断
    Candidate("bai", "glm-5.3-flash", "GLM 5.3 Flash (B.AI)", 128_000, notes="低负载恢复 1.9s"),
    Candidate("nvidia", "deepseek-ai/deepseek-v4-pro-0813", "DeepSeek V4 Pro 0813 (NVIDIA)", 1_000_000, quality_tier=2, notes="低负载恢复 31s; 2026-08-29 实测 1M ctx"),
    # nemotron-3-ultra: 动态优先级自动管理(曾 503), 恢复后自动上位
    Candidate("nvidia", "nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra (NVIDIA)", 1_000_000, quality_tier=2, notes="上游 503 曾失效"),
]

# 任务类型检测关键词（用于 harness 自动分类）
# 原则：宁可漏判落默认档，不可误判撞车（基线第 4 节教训）
TASK_KEYWORDS: dict[TaskType, list[str]] = {
    # vision 只认「明确分析已有图」的强信号；生成意图词(图表/chart/图片/照片/视觉)已移除 —— 2026-08-28 误判修复:
    #   纯文本请求只要提到"画个架构图/图表/转成图片/视觉设计"就会被误判进慢的 vision 链(deepseek-v4-flash-vision-exp 带 reasoning)。
    #   真正的带图请求由网关层 _has_images() 强制走 vision，不依赖此处关键词，故可将生成意图词安全移除。
    #   注意：detect_task_type 用字面子串匹配(kw in desc_lower)，故关键词必须是干净字面信号，不含正则/易被普通词包含的子串(如 ocr 会撞 microservice)。
    "vision": ["screenshot", "截图", "看图", "识图", "识别图片", "图像分析", "图片分析", "describe the image", "analyse the image", "analyze the image", "图像识别", "识别图中", "解析图片", "读取图片", "图片中有什么"],
    "navigation_basic": ["goto", "click", "type ", "navigate", "open ", "visit"],
    "complex_extraction": ["extract", "parse ", "schema", "table structure", "js(", "evaluate", "xpath", "css selector", "structured data", "字段", "结构化", "提取"],
    "long_running": ["loop", "iterate", "paginate", "scroll", "wait", "multi-step"],
    "fast_worker": ["quick", "simple", "single", "short", "one-shot", "快速", "简单", "单步"],
    "coding": [
        "```", "def ", "import ", "class ", "function", "refactor", "implement",
        "python", "javascript", "typescript", "golang", "rust", "c++", "sql",
        "algorithm", "complexity", "recursive", "parser", "regex",
        "debug", "traceback", "stack trace", "exception", "runtime error",
        "写代码", "代码", "算法", "调试", "报错", "函数", "脚本", "重构",
    ],
    "chinese_content": ["中文", "汉字", "简体", "繁体", "中国"],
}

# 分类阈值（与 config/harness_router.yaml 保持一致）
LONG_RUNNING_TOOL_ROUNDS = 8
LONG_RUNNING_CONTEXT_CHARS = 25_000
CHINESE_RATIO_THRESHOLD = 0.15


def detect_task_type(task_description: str, tool_calls_count: int = 0, context_chars: int = 0) -> TaskType:
    """
    根据任务描述、工具调用数、上下文长度自动判断任务类型。
    优先级：vision > long_running > chinese_content > coding > complex_extraction > fast_worker > navigation_basic
    说明：
    - vision 需强信号（screenshot/图片等），analyze 已不再是信号
    - coding 在 chinese 之后：中文占比高的请求优先走中文链（第 2 腿已升级强模型）
    - 带图请求（payload 含 image_url）在网关层强制走 vision 链，不依赖关键词
    """
    desc_lower = task_description.lower()

    # 视觉任务（强信号）
    if any(kw in desc_lower for kw in TASK_KEYWORDS["vision"]):
        return "vision"

    # 长周期任务
    if tool_calls_count >= LONG_RUNNING_TOOL_ROUNDS or context_chars > LONG_RUNNING_CONTEXT_CHARS:
        return "long_running"

    # 中文内容
    chinese_chars = sum(1 for c in task_description if '\u4e00' <= c <= '\u9fff')
    if chinese_chars / max(len(task_description), 1) > CHINESE_RATIO_THRESHOLD:
        return "chinese_content"

    # 代码/算法/调试（强模型）
    if any(kw in desc_lower for kw in TASK_KEYWORDS["coding"]):
        return "coding"

    # 复杂提取
    if any(kw in desc_lower for kw in TASK_KEYWORDS["complex_extraction"]):
        return "complex_extraction"

    # 高频短指令
    if any(kw in desc_lower for kw in TASK_KEYWORDS["fast_worker"]):
        return "fast_worker"

    # 默认导航/基础交互
    return "navigation_basic"
