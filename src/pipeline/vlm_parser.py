"""
VLM waveform parsing module.
Uses google/gemini-flash-1.5 (via OpenRouter) to parse waveform screenshots into structured JSON.
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
    """Return (base64_str, media_type) for the given image file."""
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
    """Strip <think>...</think> CoT blocks (defensive: some models may include them)."""
    if not raw:
        return ""
    match = re.search(r"<think>.*?</think>\s*(.*)", raw, re.DOTALL)
    return match.group(1).strip() if match else raw.strip()


def parse_waveform_image(
    image_path: str,
    client: OpenAI | None = None,
) -> dict:
    """
    Parse a waveform screenshot with the VLM and return a structured JSON dict.
    Falls back to {"raw_vlm_output": ..., "confidence": 0.0} on parse failure.
    """
    client = client or get_client()
    print(f"[VLM] Parsing waveform: {image_path}  (model: {VLM_MODEL})")

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

    # Strip markdown code fence if present
    json_str = re.sub(r"^```(?:json)?\n?", "", json_str)
    json_str = re.sub(r"\n?```$", "", json_str)

    try:
        parsed = json.loads(json_str)
        print(
            f"[VLM] Done | type: {parsed.get('waveform_type')} | "
            f"signals: {len(parsed.get('signals', []))} | "
            f"confidence: {parsed.get('confidence', '?')}"
        )
        return parsed
    except json.JSONDecodeError as e:
        print(f"[VLM] JSON parse failed: {e}\nRaw output:\n{json_str[:500]}")
        return {"raw_vlm_output": json_str, "confidence": 0.0}
