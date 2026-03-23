"""
Waveform Assertion Generation Pipeline
VLM: Qwen3-VL-30B-A3B-Thinking  (local vLLM) → 波形視覺解析
LLM: gpt-oss-120b                (local vLLM) → Assertion 生成 + 對話

Usage:
    python waveform_pipeline.py
"""

import base64
import json
import re
from pathlib import Path
from openai import OpenAI

# ── Endpoint 設定 ────────────────────────────────────────────────────────────
VLM_BASE_URL = "http://localhost:8000/v1"   # Qwen3-VL vLLM endpoint
LLM_BASE_URL = "http://localhost:8001/v1"   # gpt-oss-120b vLLM endpoint
VLM_MODEL    = "Qwen/Qwen3-VL-30B-A3B-Thinking"
LLM_MODEL    = "gpt-oss-120b"

vlm_client = OpenAI(base_url=VLM_BASE_URL, api_key="token-placeholder")
llm_client = OpenAI(base_url=LLM_BASE_URL, api_key="token-placeholder")


# ── Prompts ──────────────────────────────────────────────────────────────────

VLM_SYSTEM = """You are an expert EDA waveform analyzer.
Given a waveform screenshot (from Verdi, GTKWave, Virtuoso, or HSPICE), extract ALL observable information and return ONLY a valid JSON object. No markdown, no explanation outside the JSON.

JSON schema:
{
  "waveform_type": "digital" | "analog" | "mixed",
  "tool_hint": string | null,          // e.g. "Verdi", "GTKWave", "Virtuoso"
  "time_axis": {
    "unit": string,                    // e.g. "ns", "us", "ps"
    "visible_range": [start, end],     // numeric
    "grid_interval": number | null
  },
  "signals": [
    {
      "name": string,
      "type": "clock" | "single_bit" | "bus" | "analog_voltage" | "analog_current",
      "width": number | null,          // for bus
      "y_range": [min, max] | null,    // for analog
      "y_unit": string | null          // "V", "A", "mV" etc.
    }
  ],
  "events": [
    {
      "time_approx": number,
      "signal": string,
      "event": "rising_edge" | "falling_edge" | "value_change" | "glitch" | "x_state" | "anomaly",
      "value": string | null,          // hex/bin for bus, numeric for analog
      "note": string | null
    }
  ],
  "cursor_measurements": [
    {
      "type": "delta_t" | "delta_v" | "absolute",
      "value": number,
      "unit": string,
      "between": [string, string] | null,
      "signal": string | null
    }
  ],
  "clock_info": {
    "signal_name": string | null,
    "period_approx": number | null,
    "period_unit": string | null,
    "frequency_approx": string | null
  } | null,
  "protocol_hints": [string],          // e.g. ["AXI4", "SPI", "req-ack handshake"]
  "anomalies": [
    {
      "type": string,
      "signal": string,
      "time_approx": number | null,
      "description": string
    }
  ],
  "analog_features": {
    "overshoot_pct": number | null,
    "undershoot_pct": number | null,
    "settling_visible": boolean,
    "ringing_visible": boolean,
    "dc_level_approx": number | null
  } | null,
  "confidence": number,                // 0.0 - 1.0
  "parsing_notes": string | null       // 解析困難或不確定的地方
}"""

LLM_SYSTEM = """You are a senior verification engineer specializing in both digital RTL and analog/mixed-signal verification.

You will receive:
1. A structured JSON description of a waveform (extracted by a vision model)
2. The engineer's natural language description of what they want to verify
3. Conversation history

Your job:
- Generate precise, ready-to-use verification artifacts
- For DIGITAL waveforms → SystemVerilog Assertions (SVA) with property/assert structure
- For ANALOG waveforms → HSPICE/Spectre .meas statements + Python verification script
- For MIXED → both as appropriate
- Use real extracted values from the JSON where available; use named parameters where not
- After generating, briefly explain each assertion in Traditional Chinese
- Proactively suggest 1-2 additional checks the engineer might have missed
- If waveform_type is unclear, ask one focused clarifying question

Format rules:
- Wrap all code in triple backticks with language tag (systemverilog / spice / python)
- Keep explanations concise and technical
- Use Traditional Chinese for all prose explanations"""


# ── Step 1: VLM 波形解析 ─────────────────────────────────────────────────────

def encode_image(image_path: str) -> str:
    """將圖片轉為 base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def parse_waveform_image(image_path: str) -> dict:
    """
    用 Qwen3-VL-Thinking 解析波形截圖
    Thinking mode: /think 觸發 CoT，讓 VLM 仔細分析後再輸出 JSON
    """
    print(f"[VLM] 解析波形截圖: {image_path}")

    ext = Path(image_path).suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }.get(ext, "image/png")

    b64 = encode_image(image_path)

    # Qwen3-VL Thinking mode: 在 user message 加 /think 觸發 CoT
    response = vlm_client.chat.completions.create(
        model=VLM_MODEL,
        messages=[
            {"role": "system", "content": VLM_SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64}",
                            "detail": "high",   # 高解析度分析模式
                        },
                    },
                    {
                        "type": "text",
                        "text": "/think\nAnalyze this waveform screenshot carefully and return the JSON.",
                    },
                ],
            },
        ],
        temperature=0.1,   # 低 temperature 讓解析更穩定
        max_tokens=4096,
    )

    raw = response.choices[0].message.content

    # 從 Thinking model 的輸出中提取 JSON
    # Qwen3 Thinking 格式: <think>...</think> 後面才是實際輸出
    think_match = re.search(r"<think>.*?</think>\s*(.*)", raw, re.DOTALL)
    json_str = think_match.group(1).strip() if think_match else raw.strip()

    # 清理可能的 markdown code fence
    json_str = re.sub(r"^```(?:json)?\n?", "", json_str)
    json_str = re.sub(r"\n?```$", "", json_str)

    try:
        parsed = json.loads(json_str)
        print(f"[VLM] 解析完成 | 類型: {parsed.get('waveform_type')} | "
              f"信號數: {len(parsed.get('signals', []))} | "
              f"信心度: {parsed.get('confidence', '?')}")
        return parsed
    except json.JSONDecodeError as e:
        print(f"[VLM] JSON 解析失敗: {e}")
        print(f"[VLM] 原始輸出:\n{json_str[:500]}")
        # 降級處理：回傳原始文字讓 LLM 自行解讀
        return {"raw_vlm_output": json_str, "confidence": 0.0}


# ── Step 2: LLM Assertion 生成 ───────────────────────────────────────────────

class AssertionSession:
    """
    維護與 gpt-oss-120b 的對話狀態
    支援多輪對話精煉 assertion
    """

    def __init__(self):
        self.history = []
        self.waveform_context: dict | None = None
        self.waveform_summary: str = ""

    def set_waveform(self, vlm_result: dict):
        """注入波形解析結果作為 session context"""
        self.waveform_context = vlm_result
        wt = vlm_result.get("waveform_type", "unknown")
        signals = [s["name"] for s in vlm_result.get("signals", [])]
        hints = vlm_result.get("protocol_hints", [])
        anomalies = vlm_result.get("anomalies", [])
        confidence = vlm_result.get("confidence", 0)

        self.waveform_summary = (
            f"[波形解析結果]\n"
            f"類型: {wt}\n"
            f"信號: {', '.join(signals) if signals else '未識別'}\n"
            f"協議提示: {', '.join(hints) if hints else '無'}\n"
            f"異常: {len(anomalies)} 個\n"
            f"VLM 信心度: {confidence:.0%}\n"
            f"\n完整 VLM JSON:\n{json.dumps(vlm_result, ensure_ascii=False, indent=2)}"
        )

        print(f"\n[LLM] 波形 context 已載入")
        print(f"      類型: {wt} | 信號: {signals} | 協議: {hints}")

        # 把波形摘要作為第一條 assistant 訊息展示給工程師
        summary_msg = self._build_waveform_summary_message(vlm_result, signals, hints, anomalies)
        return summary_msg

    def _build_waveform_summary_message(self, vlm, signals, hints, anomalies):
        wt = vlm.get("waveform_type", "unknown")
        clock = vlm.get("clock_info")
        cursors = vlm.get("cursor_measurements", [])
        analog = vlm.get("analog_features")
        note = vlm.get("parsing_notes")
        confidence = vlm.get("confidence", 0)

        lines = [f"**波形截圖已解析完成** (VLM 信心度: {confidence:.0%})\n"]
        lines.append(f"**類型：** {wt}")

        if signals:
            lines.append(f"**識別信號：** {', '.join(f'`{s}`' for s in signals)}")

        if clock and clock.get("signal_name"):
            lines.append(f"**時脈：** `{clock['signal_name']}` "
                        f"≈ {clock.get('frequency_approx', '?')}")

        if hints:
            lines.append(f"**協議特徵：** {', '.join(hints)}")

        if cursors:
            for c in cursors:
                lines.append(f"**量測：** ΔT = {c['value']} {c['unit']}")

        if analog:
            features = []
            if analog.get("overshoot_pct"):
                features.append(f"overshoot {analog['overshoot_pct']:.1f}%")
            if analog.get("ringing_visible"):
                features.append("ringing 可見")
            if analog.get("settling_visible"):
                features.append("settling 行為可見")
            if features:
                lines.append(f"**類比特徵：** {', '.join(features)}")

        if anomalies:
            lines.append(f"**⚠️ 異常：** 偵測到 {len(anomalies)} 個異常點")

        if note:
            lines.append(f"**解析備註：** {note}")

        lines.append("\n請描述您想驗證什麼，我來生成對應的 assertion 或量測腳本。")
        return "\n".join(lines)

    def chat(self, user_message: str) -> str:
        """
        送出訊息給 gpt-oss-120b，維護完整對話歷史
        """
        # 構建送給 LLM 的訊息
        # 第一輪：把完整 VLM JSON 附在 user 訊息後面
        if not self.history and self.waveform_context:
            full_user_msg = f"{user_message}\n\n{self.waveform_summary}"
        else:
            full_user_msg = user_message

        self.history.append({"role": "user", "content": full_user_msg})

        print(f"\n[LLM] 呼叫 gpt-oss-120b...")

        response = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": LLM_SYSTEM},
                *self.history,
            ],
            temperature=0.2,
            max_tokens=4096,
            # gpt-oss-120b 支援 configurable reasoning
            # 對 assertion 生成用 "high" reasoning 確保邏輯嚴謹
            extra_body={"reasoning_effort": "high"},
        )

        assistant_msg = response.choices[0].message.content

        # 儲存 assistant 回覆（不含 waveform context，避免 history 過長）
        self.history.append({"role": "assistant", "content": assistant_msg})

        # Token 使用統計
        usage = response.usage
        if usage:
            print(f"[LLM] Tokens: input={usage.prompt_tokens}, "
                  f"output={usage.completion_tokens}")

        return assistant_msg


# ── Step 3: 互動式 CLI ───────────────────────────────────────────────────────

def run_interactive(image_path: str | None = None):
    """
    主要互動 loop
    """
    print("=" * 60)
    print("  Waveform Assertion Assistant")
    print("  VLM: Qwen3-VL-30B-A3B-Thinking")
    print("  LLM: gpt-oss-120b")
    print("=" * 60)

    session = AssertionSession()

    # ── 載入波形截圖 ──
    if image_path:
        path = image_path
    else:
        path = input("\n請輸入波形截圖路徑 (或直接 Enter 跳過進入純文字模式): ").strip()

    if path and Path(path).exists():
        vlm_result = parse_waveform_image(path)
        summary = session.set_waveform(vlm_result)
        print(f"\n{'─'*60}")
        print("[Assistant]")
        print(summary)
        print(f"{'─'*60}")
    else:
        if path:
            print(f"[警告] 找不到檔案: {path}，進入純文字模式")
        print("\n[純文字模式] 請直接描述波形行為或貼入信號清單")

    # ── 對話 loop ──
    print("\n輸入 'quit' 離開，'reset' 重新載入截圖，'save' 儲存 assertion\n")

    saved_assertions = []

    while True:
        try:
            user_input = input("您: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再見！")
            break

        if not user_input:
            continue

        if user_input.lower() == "quit":
            break

        if user_input.lower() == "reset":
            new_path = input("新截圖路徑: ").strip()
            if Path(new_path).exists():
                session = AssertionSession()
                vlm_result = parse_waveform_image(new_path)
                summary = session.set_waveform(vlm_result)
                print(f"\n[Assistant]\n{summary}\n")
            continue

        if user_input.lower() == "save":
            out_path = "assertions_output.sv"
            with open(out_path, "w") as f:
                for i, a in enumerate(saved_assertions):
                    f.write(f"// === Assertion {i+1} ===\n{a}\n\n")
            print(f"[已儲存] {out_path}")
            continue

        # ── 主要對話 ──
        response = session.chat(user_input)
        print(f"\n[Assistant]\n{response}\n")

        # 自動收集 code block
        code_blocks = re.findall(r"```\w+\n(.*?)```", response, re.DOTALL)
        saved_assertions.extend(code_blocks)


# ── Batch 模式（非互動，適合 CI 整合）───────────────────────────────────────

def run_batch(image_path: str, prompts: list[str]) -> list[str]:
    """
    非互動模式：給定截圖 + 一組 prompts，回傳所有 assertions
    適合整合進 regression pipeline
    """
    vlm_result = parse_waveform_image(image_path)
    session = AssertionSession()
    session.set_waveform(vlm_result)

    results = []
    for prompt in prompts:
        print(f"\n[Batch] Prompt: {prompt}")
        response = session.chat(prompt)
        results.append(response)

    return results


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        run_interactive(image_path=sys.argv[1])
    else:
        run_interactive()
