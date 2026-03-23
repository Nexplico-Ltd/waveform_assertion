"""
Conversation state management.
Maintains VLM context and LLM multi-turn history; supports interactive CLI mode.
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
        """Parse a waveform screenshot and return a markdown summary message."""
        vlm_result = parse_waveform_image(image_path, client=self.client)
        return self.set_waveform(vlm_result)

    def auto_brainstorm(self) -> str:
        """
        Automatically analyze the loaded waveform and suggest possible assertions.
        Called after set_waveform(); result becomes the first assistant message.
        """
        if not self.waveform_context:
            return ""

        brainstorm_prompt = (
            "Review the waveform analysis below and brainstorm possible verification checks.\n"
            "Present each idea as a bullet point with a brief explanation of what it verifies "
            "and why it matters. Do not generate code yet — focus on ideas.\n\n"
            + self._waveform_summary
        )

        self.history.append({"role": "user", "content": brainstorm_prompt})
        content, usage = generate_assertion(self.history, client=self.client)
        self.history.append({"role": "assistant", "content": content})

        if usage:
            print(
                f"[LLM] Brainstorm tokens: input={usage['prompt_tokens']}, "
                f"output={usage['completion_tokens']}"
            )
        return content

    def set_waveform(self, vlm_result: dict) -> str:
        """Inject VLM parse result and return a markdown summary."""
        self.waveform_context = vlm_result
        wt = vlm_result.get("waveform_type", "unknown")
        signals = [s["name"] for s in vlm_result.get("signals", [])]
        hints = vlm_result.get("protocol_hints", [])
        anomalies = vlm_result.get("anomalies", [])
        confidence = vlm_result.get("confidence", 0)

        self._waveform_summary = (
            f"[Waveform Analysis]\n"
            f"Type: {wt}\n"
            f"Signals: {', '.join(signals) if signals else 'none identified'}\n"
            f"Protocol hints: {', '.join(hints) if hints else 'none'}\n"
            f"Anomalies: {len(anomalies)}\n"
            f"VLM confidence: {confidence:.0%}\n"
            f"\nFull VLM JSON:\n{json.dumps(vlm_result, ensure_ascii=False, indent=2)}"
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

        lines = [f"**Waveform parsed successfully** (VLM confidence: {confidence:.0%})\n"]
        lines.append(f"**Type:** {wt}")
        if signals:
            lines.append(f"**Signals:** {', '.join(f'`{s}`' for s in signals)}")
        if clock and clock.get("signal_name"):
            lines.append(
                f"**Clock:** `{clock['signal_name']}` ≈ {clock.get('frequency_approx', '?')}"
            )
        if hints:
            lines.append(f"**Protocol hints:** {', '.join(hints)}")
        for c in cursors:
            lines.append(f"**Measurement:** ΔT = {c['value']} {c['unit']}")
        if analog:
            features = []
            if analog.get("overshoot_pct"):
                features.append(f"overshoot {analog['overshoot_pct']:.1f}%")
            if analog.get("ringing_visible"):
                features.append("ringing visible")
            if analog.get("settling_visible"):
                features.append("settling visible")
            if features:
                lines.append(f"**Analog features:** {', '.join(features)}")
        if anomalies:
            lines.append(f"**Anomalies:** {len(anomalies)} detected")
        if note:
            lines.append(f"**Parsing notes:** {note}")
        lines.append("\nDescribe what you want to verify and I will generate the corresponding assertions or measurement scripts.")
        return "\n".join(lines)

    def chat(self, user_message: str) -> str:
        """Send a message to the LLM and maintain full conversation history."""
        # First turn: append the full VLM JSON to the user message
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

        # Auto-collect code blocks
        code_blocks = re.findall(r"```\w+\n(.*?)```", content, re.DOTALL)
        self.collected_code.extend(code_blocks)

        return content

    def save_assertions(self, output_path: str | None = None) -> int:
        """Save all collected code blocks. Returns the number saved."""
        if not self.collected_code:
            print("[Session] No assertions to save.")
            return 0
        OUTPUT_DIR.mkdir(exist_ok=True)
        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(OUTPUT_DIR / f"assertions_{ts}.sv")
        with open(output_path, "w", encoding="utf-8") as f:
            for i, block in enumerate(self.collected_code):
                f.write(f"// === Assertion {i + 1} ===\n{block}\n\n")
        print(f"[Session] Saved {len(self.collected_code)} assertion(s) → {output_path}")
        return len(self.collected_code)

    def reset(self):
        """Clear conversation history (waveform context is preserved)."""
        self.history.clear()
        self.collected_code.clear()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _run_cli(image_path: str | None = None) -> None:
    print("=" * 60)
    print("  Waveform Assertion Assistant")
    print("  VLM: google/gemini-flash-1.5 (OpenRouter)")
    print("  LLM: anthropic/claude-3.5-haiku (OpenRouter)")
    print("=" * 60)

    session = AssertionSession()

    path = image_path or input("\nWaveform screenshot path (Enter to skip): ").strip()

    if path and Path(path).exists():
        summary = session.load_image(path)
        print(f"\n{'─'*60}\n[Assistant]\n{summary}\n{'─'*60}")
    elif path:
        print(f"[Warning] File not found: {path}. Running in text-only mode.")

    print("\nCommands: 'quit' | 'save' | 'reset'\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
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
            print("[Session] Conversation reset.")
            continue

        response = session.chat(user_input)
        print(f"\n[Assistant]\n{response}\n")


if __name__ == "__main__":
    import sys
    _run_cli(image_path=sys.argv[1] if len(sys.argv) > 1 else None)
