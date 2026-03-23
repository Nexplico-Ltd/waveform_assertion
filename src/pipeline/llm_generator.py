"""
LLM Assertion 生成模組
使用 anthropic/claude-3.5-haiku（via OpenRouter）根據 VLM JSON + 工程師意圖生成 assertion
"""

from pathlib import Path

from openai import OpenAI

from .config import get_client, LLM_MODEL

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_system_prompt() -> str:
    return (_PROMPTS_DIR / "llm_system.md").read_text(encoding="utf-8")


def generate_assertion(
    messages: list[dict],
    client: OpenAI | None = None,
) -> tuple[str, dict]:
    """
    呼叫 LLM 生成 assertion。

    Args:
        messages: 對話歷史（不含 system prompt，由此函式注入）
        client:   OpenAI client，None 時自動建立

    Returns:
        (assistant_content, usage_stats)
    """
    client = client or get_client()

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _load_system_prompt()},
            *messages,
        ],
        temperature=0.2,
        max_tokens=4096,
    )

    content = response.choices[0].message.content
    usage: dict = {}
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        }
    return content, usage
