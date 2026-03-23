"""
LLM assertion generation module.
Uses anthropic/claude-3.5-haiku (via OpenRouter) to generate assertions from VLM JSON and engineer intent.
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
    Call the LLM to generate assertions.

    Args:
        messages: Conversation history (without system prompt; injected here).
        client:   OpenAI client; created automatically if None.

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
