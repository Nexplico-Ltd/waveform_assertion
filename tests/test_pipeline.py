"""
Pipeline unit tests.
All OpenRouter endpoints are mocked — no real API key required.
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
    """Build a mock OpenAI chat completion response."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 200
    return resp


# ── VLM Parser tests ──────────────────────────────────────────────────────────

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
        """VLM returns clean JSON directly."""
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
        """VLM output contains a <think> block that should be stripped."""
        img = tmp_path / "wave.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            f"<think>analyzing waveform...</think>\n{json.dumps(SAMPLE_VLM_RESULT)}"
        )

        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "digital"

    def test_json_with_code_fence(self, tmp_path):
        """VLM output is wrapped in a ```json code fence."""
        img = tmp_path / "wave.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            f"```json\n{json.dumps(SAMPLE_VLM_RESULT)}\n```"
        )

        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "digital"

    def test_json_parse_error_fallback(self, tmp_path):
        """VLM returns invalid JSON → fallback to raw output."""
        img = tmp_path / "wave.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "Sorry, I cannot analyze this image."
        )

        result = parse_waveform_image(str(img), client=mock_client)
        assert result["confidence"] == 0.0
        assert "raw_vlm_output" in result


# ── Session tests ─────────────────────────────────────────────────────────────

class TestAssertionSession:
    def test_set_waveform_returns_summary(self):
        session = AssertionSession()
        summary = session.set_waveform(SAMPLE_VLM_RESULT)
        assert "digital" in summary
        assert "clk" in summary
        assert "92%" in summary

    def test_set_waveform_low_confidence_note(self):
        low_conf = {**SAMPLE_VLM_RESULT, "confidence": 0.3, "parsing_notes": "blurry screenshot"}
        session = AssertionSession()
        summary = session.set_waveform(low_conf)
        assert "30%" in summary
        assert "blurry screenshot" in summary

    def test_chat_first_turn_includes_vlm_context(self):
        """First chat turn must append the full VLM JSON to the user message."""
        session = AssertionSession()
        session.set_waveform(SAMPLE_VLM_RESULT)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "```systemverilog\nassert property (@(posedge clk) req |-> ##[1:5] ack);\n```"
        )
        session.client = mock_client

        session.chat("Verify req-ack handshake")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "Waveform Analysis" in user_msg["content"] or "VLM JSON" in user_msg["content"]

    def test_chat_collects_code_blocks(self):
        """Code blocks in LLM replies should be auto-collected."""
        session = AssertionSession()
        session.set_waveform(SAMPLE_VLM_RESULT)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "Here is the generated assertion:\n"
            "```systemverilog\n"
            "assert property (@(posedge clk) req |-> ##[1:5] ack);\n"
            "```"
        )
        session.client = mock_client

        session.chat("Generate req-ack assertion")
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
