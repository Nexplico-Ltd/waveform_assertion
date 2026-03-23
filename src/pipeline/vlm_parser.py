"""
VLM 波形解析模組
使用 google/gemini-flash-1.5（via OpenRouter）解析波形截圖 → 結構化 JSON
"""

import base64
import json
import re
from pathlib import Path

from openai import OpenAI

from .config import get_client, VLM_MODEL

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_system_prompt() -> str:
    return (_PROMPTS_DIR / "vlm_system.md").read_text(encoding="utf-8")


def encode_image(image_path: str) -> tuple[str, str]:
    """回傳 (base64_str, media_type)"""
    ext = Path(image_path).suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8"), media_type


def strip_thinking(raw: str | None) -> str:
    """剝離 <think>...</think> CoT block（防禦性處理，部分模型可能輸出）"""
    if not raw:
        return ""
    match = re.search(r"<think>.*?</think>\s*(.*)", raw, re.DOTALL)
    return match.group(1).strip() if match else raw.strip()


def parse_waveform_image(
    image_path: str,
    client: OpenAI | None = None,
) -> dict:
    """
    用 VLM 解析波形截圖，回傳結構化 JSON dict。
    失敗時降級回傳 {"raw_vlm_output": ..., "confidence": 0.0}
    """
    client = client or get_client()
    print(f"[VLM] 解析波形截圖: {image_path}  (model: {VLM_MODEL})")

    b64, media_type = encode_image(image_path)

    response = client.chat.completions.create(
        model=VLM_MODEL,
        messages=[
            {"role": "system", "content": _load_system_prompt()},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64}",
                            "detail": "high",
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyze this waveform screenshot carefully and return the JSON.",
                    },
                ],
            },
        ],
        temperature=0.1,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content
    json_str = strip_thinking(raw)

    # 清理 markdown code fence
    json_str = re.sub(r"^```(?:json)?\n?", "", json_str)
    json_str = re.sub(r"\n?```$", "", json_str)

    try:
        parsed = json.loads(json_str)
        print(
            f"[VLM] 解析完成 | 類型: {parsed.get('waveform_type')} | "
            f"信號數: {len(parsed.get('signals', []))} | "
            f"信心度: {parsed.get('confidence', '?')}"
        )
        return parsed
    except json.JSONDecodeError as e:
        print(f"[VLM] JSON 解析失敗: {e}\n原始輸出:\n{json_str[:500]}")
        return {"raw_vlm_output": json_str, "confidence": 0.0}
