"""
對話狀態管理
維護 VLM context + LLM 多輪對話歷史，支援 CLI 互動模式
"""

import json
import re
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from .vlm_parser import parse_waveform_image
from .llm_generator import generate_assertion

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


class AssertionSession:
    def __init__(self, client: OpenAI | None = None):
        self.client = client
        self.history: list[dict] = []
        self.waveform_context: dict | None = None
        self._waveform_summary: str = ""
        self.collected_code: list[str] = []

    def load_image(self, image_path: str) -> str:
        """解析波形截圖，回傳 markdown 摘要訊息"""
        vlm_result = parse_waveform_image(image_path, client=self.client)
        return self.set_waveform(vlm_result)

    def set_waveform(self, vlm_result: dict) -> str:
        """注入 VLM 解析結果，回傳 markdown 摘要"""
        self.waveform_context = vlm_result
        wt = vlm_result.get("waveform_type", "unknown")
        signals = [s["name"] for s in vlm_result.get("signals", [])]
        hints = vlm_result.get("protocol_hints", [])
        anomalies = vlm_result.get("anomalies", [])
        confidence = vlm_result.get("confidence", 0)

        self._waveform_summary = (
            f"[波形解析結果]\n"
            f"類型: {wt}\n"
            f"信號: {', '.join(signals) if signals else '未識別'}\n"
            f"協議提示: {', '.join(hints) if hints else '無'}\n"
            f"異常: {len(anomalies)} 個\n"
            f"VLM 信心度: {confidence:.0%}\n"
            f"\n完整 VLM JSON:\n{json.dumps(vlm_result, ensure_ascii=False, indent=2)}"
        )

        return self._build_summary_message(vlm_result, signals, hints, anomalies)

    def _build_summary_message(
        self, vlm: dict, signals: list, hints: list, anomalies: list
    ) -> str:
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
            lines.append(
                f"**時脈：** `{clock['signal_name']}` ≈ {clock.get('frequency_approx', '?')}"
            )
        if hints:
            lines.append(f"**協議特徵：** {', '.join(hints)}")
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
            lines.append(f"**⚠ 異常：** 偵測到 {len(anomalies)} 個異常點")
        if note:
            lines.append(f"**解析備註：** {note}")
        lines.append("\n請描述您想驗證什麼，我來生成對應的 assertion 或量測腳本。")
        return "\n".join(lines)

    def chat(self, user_message: str) -> str:
        """送出訊息給 LLM，維護完整對話歷史"""
        # 第一輪：把完整 VLM JSON 附在 user 訊息後面
        if not self.history and self.waveform_context:
            full_user_msg = f"{user_message}\n\n{self._waveform_summary}"
        else:
            full_user_msg = user_message

        self.history.append({"role": "user", "content": full_user_msg})

        content, usage = generate_assertion(self.history, client=self.client)

        self.history.append({"role": "assistant", "content": content})

        if usage:
            print(
                f"[LLM] Tokens: input={usage['prompt_tokens']}, "
                f"output={usage['completion_tokens']}"
            )

        # 自動收集 code block
        code_blocks = re.findall(r"```\w+\n(.*?)```", content, re.DOTALL)
        self.collected_code.extend(code_blocks)

        return content

    def save_assertions(self, output_path: str | None = None) -> int:
        """儲存所有收集到的 code block，回傳儲存數量"""
        if not self.collected_code:
            print("[Session] 尚無 assertion 可儲存")
            return 0
        OUTPUT_DIR.mkdir(exist_ok=True)
        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(OUTPUT_DIR / f"assertions_{ts}.sv")
        with open(output_path, "w", encoding="utf-8") as f:
            for i, block in enumerate(self.collected_code):
                f.write(f"// === Assertion {i + 1} ===\n{block}\n\n")
        print(f"[Session] 已儲存 {len(self.collected_code)} 個 assertion → {output_path}")
        return len(self.collected_code)

    def reset(self):
        """清空對話歷史（保留 waveform context）"""
        self.history.clear()
        self.collected_code.clear()


# ── CLI 互動模式 ──────────────────────────────────────────────────────────────

def _run_cli(image_path: str | None = None) -> None:
    print("=" * 60)
    print("  Waveform Assertion Assistant")
    print(f"  VLM: google/gemini-flash-1.5 (OpenRouter)")
    print(f"  LLM: anthropic/claude-3.5-haiku (OpenRouter)")
    print("=" * 60)

    session = AssertionSession()

    path = image_path or input("\n請輸入波形截圖路徑 (Enter 跳過): ").strip()

    if path and Path(path).exists():
        summary = session.load_image(path)
        print(f"\n{'─'*60}\n[Assistant]\n{summary}\n{'─'*60}")
    elif path:
        print(f"[警告] 找不到檔案: {path}，進入純文字模式")

    print("\n輸入 'quit' 離開 | 'save' 儲存 assertion | 'reset' 清空對話\n")

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
        if user_input.lower() == "save":
            session.save_assertions()
            continue
        if user_input.lower() == "reset":
            session.reset()
            print("[Session] 對話已重置")
            continue

        response = session.chat(user_input)
        print(f"\n[Assistant]\n{response}\n")


if __name__ == "__main__":
    import sys
    _run_cli(image_path=sys.argv[1] if len(sys.argv) > 1 else None)
