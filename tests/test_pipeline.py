"""
Pipeline 單元測試
mock OpenRouter 端點，不需要真實 API key
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.vlm_parser import strip_thinking, parse_waveform_image
from pipeline.session import AssertionSession


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_VLM_RESULT = {
    "waveform_type": "digital",
    "tool_hint": "GTKWave",
    "time_axis": {"unit": "ns", "visible_range": [0, 100], "grid_interval": 10},
    "signals": [
        {"name": "clk", "type": "clock", "width": None, "y_range": None, "y_unit": None},
        {"name": "req", "type": "single_bit", "width": None, "y_range": None, "y_unit": None},
        {"name": "ack", "type": "single_bit", "width": None, "y_range": None, "y_unit": None},
    ],
    "events": [
        {"time_approx": 10, "signal": "req", "event": "rising_edge", "value": None, "note": None},
        {"time_approx": 20, "signal": "ack", "event": "rising_edge", "value": None, "note": None},
    ],
    "cursor_measurements": [{"type": "delta_t", "value": 10, "unit": "ns", "between": ["req", "ack"], "signal": None}],
    "clock_info": {"signal_name": "clk", "period_approx": 10, "period_unit": "ns", "frequency_approx": "100MHz"},
    "protocol_hints": ["req-ack handshake"],
    "anomalies": [],
    "analog_features": None,
    "confidence": 0.92,
    "parsing_notes": None,
}


def _make_mock_response(content: str) -> MagicMock:
    """建立 mock OpenAI response"""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 200
    return resp


# ── VLM Parser 測試 ───────────────────────────────────────────────────────────

class TestStripThinking:
    def test_strips_think_block(self):
        raw = "<think>lots of reasoning here...</think>\n{\"key\": \"value\"}"
        assert strip_thinking(raw) == '{"key": "value"}'

    def test_no_think_block(self):
        raw = '{"key": "value"}'
        assert strip_thinking(raw) == '{"key": "value"}'

    def test_multiline_think_block(self):
        raw = "<think>\nline 1\nline 2\n</think>\nresult"
        assert strip_thinking(raw) == "result"


class TestParseWaveformImage:
    def test_clean_json_response(self, tmp_path):
        """VLM 直接回傳乾淨 JSON"""
        img = tmp_path / "wave.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)  # minimal PNG header

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            json.dumps(SAMPLE_VLM_RESULT)
        )

        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "digital"
        assert len(result["signals"]) == 3
        assert result["confidence"] == 0.92

    def test_json_with_think_block(self, tmp_path):
        """VLM 輸出含 <think> block，應自動剝離"""
        img = tmp_path / "wave.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            f"<think>analyzing waveform...</think>\n{json.dumps(SAMPLE_VLM_RESULT)}"
        )

        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "digital"

    def test_json_with_code_fence(self, tmp_path):
        """VLM 輸出包在 ```json 裡"""
        img = tmp_path / "wave.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            f"```json\n{json.dumps(SAMPLE_VLM_RESULT)}\n```"
        )

        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "digital"

    def test_json_parse_error_fallback(self, tmp_path):
        """VLM 回傳壞 JSON → 降級處理"""
        img = tmp_path / "wave.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "Sorry, I cannot analyze this image."
        )

        result = parse_waveform_image(str(img), client=mock_client)
        assert result["confidence"] == 0.0
        assert "raw_vlm_output" in result


# ── Session 測試 ──────────────────────────────────────────────────────────────

class TestAssertionSession:
    def test_set_waveform_returns_summary(self):
        session = AssertionSession()
        summary = session.set_waveform(SAMPLE_VLM_RESULT)
        assert "digital" in summary
        assert "clk" in summary
        assert "92%" in summary

    def test_set_waveform_low_confidence_note(self):
        low_conf = {**SAMPLE_VLM_RESULT, "confidence": 0.3, "parsing_notes": "模糊截圖"}
        session = AssertionSession()
        summary = session.set_waveform(low_conf)
        assert "30%" in summary
        assert "模糊截圖" in summary

    def test_chat_first_turn_includes_vlm_context(self):
        """第一輪對話應將 VLM JSON 附在 user 訊息後"""
        session = AssertionSession()
        session.set_waveform(SAMPLE_VLM_RESULT)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "```systemverilog\nassert property (@(posedge clk) req |-> ##[1:5] ack);\n```"
        )
        session.client = mock_client

        session.chat("驗證 req-ack 握手")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "VLM JSON" in user_msg["content"] or "波形解析結果" in user_msg["content"]

    def test_chat_collects_code_blocks(self):
        """LLM 回覆中的 code block 應被自動收集"""
        session = AssertionSession()
        session.set_waveform(SAMPLE_VLM_RESULT)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "以下是生成的 assertion：\n"
            "```systemverilog\n"
            "assert property (@(posedge clk) req |-> ##[1:5] ack);\n"
            "```"
        )
        session.client = mock_client

        session.chat("生成 req-ack assertion")
        assert len(session.collected_code) == 1
        assert "req" in session.collected_code[0]

    def test_reset_clears_history(self):
        session = AssertionSession()
        session.history = [{"role": "user", "content": "test"}]
        session.collected_code = ["some code"]
        session.reset()
        assert session.history == []
        assert session.collected_code == []

    def test_save_assertions_no_code(self, tmp_path):
        session = AssertionSession()
        count = session.save_assertions(str(tmp_path / "out.sv"))
        assert count == 0

    def test_save_assertions_writes_file(self, tmp_path):
        session = AssertionSession()
        session.collected_code = ["assert prop1;", "assert prop2;"]
        out = tmp_path / "out.sv"
        count = session.save_assertions(str(out))
        assert count == 2
        content = out.read_text()
        assert "Assertion 1" in content
        assert "Assertion 2" in content
