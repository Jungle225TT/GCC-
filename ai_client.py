"""
ai_client.py — AI 接口抽象层
支持 DeepSeek（默认）和 Anthropic Claude，通过环境变量切换

切换方式：
  # 使用 DeepSeek（默认，需安装 openai 包）
  export DEEPSEEK_API_KEY="sk-xxxxx"
  pip install openai

  # 使用 Anthropic Claude
  export AI_PROVIDER=anthropic
  export ANTHROPIC_API_KEY="sk-ant-xxxxx"
  pip install anthropic
"""

import os

# ── 当前使用的 Provider ──────────────────────────────────────────
AI_PROVIDER = os.environ.get("AI_PROVIDER", "deepseek").lower()

# ── 模型映射：fast = 分类/翻译，smart = 研究简报 ─────────────────
MODELS = {
    "deepseek": {
        "fast":  "deepseek-chat",   # DeepSeek-V3.2，适合批量任务
        "smart": "deepseek-chat",   # 同模型，上下文够长，简报质量佳
    },
    "anthropic": {
        "fast":  "claude-haiku-4-5-20251001",
        "smart": "claude-sonnet-4-20250514",
    },
}

# ── 检测 SDK 是否已安装 ──────────────────────────────────────────
HAS_AI = False
_missing_sdk = ""

if AI_PROVIDER == "deepseek":
    try:
        from openai import OpenAI as _OpenAI
        HAS_AI = True
    except ImportError:
        _missing_sdk = "openai"
elif AI_PROVIDER == "anthropic":
    try:
        import anthropic as _anthropic
        HAS_AI = True
    except ImportError:
        _missing_sdk = "anthropic"
else:
    _missing_sdk = f"未知 provider: {AI_PROVIDER}（可选 deepseek / anthropic）"

if not HAS_AI and _missing_sdk:
    print(f"⚠️  AI 不可用：缺少 {_missing_sdk} 包\n   pip install {_missing_sdk}\n")


# ── 公共接口 ─────────────────────────────────────────────────────

def check_ready(api_key=None) -> tuple[bool, str]:
    """
    检查 AI 是否可用。
    返回 (True, api_key) 或 (False, 错误提示)。
    接口与原 check_ai_ready() 兼容。
    """
    if not HAS_AI:
        sdk = "openai" if AI_PROVIDER == "deepseek" else "anthropic"
        return False, f"❌ 未安装 {sdk} 包\n   pip install {sdk}"

    if AI_PROVIDER == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY") or api_key
        if not key:
            return False, (
                "❌ 未设置 DeepSeek API Key\n"
                "   export DEEPSEEK_API_KEY=\"sk-xxxxx\"\n"
                "   或 --api-key sk-xxxxx"
            )
    else:
        key = os.environ.get("ANTHROPIC_API_KEY") or api_key
        if not key:
            return False, (
                "❌ 未设置 Anthropic API Key\n"
                "   export ANTHROPIC_API_KEY=\"sk-ant-xxxxx\"\n"
                "   或 --api-key sk-ant-xxxxx"
            )

    return True, key


def create_client(api_key: str):
    """创建并返回 AI 客户端实例"""
    if AI_PROVIDER == "deepseek":
        from openai import OpenAI
        return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    else:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)


def chat(client, prompt: str, tier: str = "fast", max_tokens: int = 1000) -> str:
    """
    统一调用接口，返回模型响应文本。

    参数：
        client    : create_client() 返回的实例
        prompt    : 用户消息（系统提示写入 prompt 即可）
        tier      : "fast"（分类/翻译）或 "smart"（研究简报）
        max_tokens: 最大输出长度
    """
    model = MODELS[AI_PROVIDER][tier]

    if AI_PROVIDER == "deepseek":
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            stream=False,
        )
        return response.choices[0].message.content

    else:  # anthropic
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text


def provider_info() -> str:
    """返回当前 provider 的展示字符串，用于启动日志"""
    model_fast = MODELS.get(AI_PROVIDER, {}).get("fast", "?")
    model_smart = MODELS.get(AI_PROVIDER, {}).get("smart", "?")
    return f"{AI_PROVIDER.upper()} ({model_fast} / {model_smart})"
