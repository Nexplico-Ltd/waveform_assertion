"""
Pipeline unit tests.
All OpenRouter endpoints are mocked — no real API key required.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from pipeline.vlm_parser import strip_thinking, parse_waveform_image, encode_image
from pipeline.llm_generator import generate_assertion
from pipeline.session import AssertionSession

SAMPLE_WAVEFORMS = Path(__file__).parent / "sample_waveforms"
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


# ── Shared fixtures ───────────────────────────────────────────────────────────

DIGITAL_VLM_RESULT = {
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
    "cursor_measurements": [
        {"type": "delta_t", "value": 10, "unit": "ns", "between": ["req", "ack"], "signal": None}
    ],
    "clock_info": {
        "signal_name": "clk", "period_approx": 10,
        "period_unit": "ns", "frequency_approx": "100MHz",
    },
    "protocol_hints": ["req-ack handshake"],
    "anomalies": [],
    "analog_features": None,
    "confidence": 0.92,
    "parsing_notes": None,
}

ANALOG_VLM_RESULT = {
    "waveform_type": "analog",
    "tool_hint": "Virtuoso",
    "time_axis": {"unit": "ns", "visible_range": [0, 200], "grid_interval": 20},
    "signals": [
        {"name": "VDD", "type": "analog_voltage", "width": None, "y_range": [0, 1.8], "y_unit": "V"},
    ],
    "events": [],
    "cursor_measurements": [],
    "clock_info": None,
    "protocol_hints": [],
    "anomalies": [],
    "analog_features": {
        "overshoot_pct": 8.5,
        "undershoot_pct": None,
        "settling_visible": True,
        "ringing_visible": True,
        "dc_level_approx": 1.8,
    },
    "confidence": 0.85,
    "parsing_notes": None,
}

MIXED_VLM_RESULT = {
    **DIGITAL_VLM_RESULT,
    "waveform_type": "mixed",
    "signals": DIGITAL_VLM_RESULT["signals"] + [
        {"name": "VREF", "type": "analog_voltage", "width": None, "y_range": [0, 1.2], "y_unit": "V"},
    ],
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


def _make_image(tmp_path: Path, name: str = "wave.png") -> Path:
    p = tmp_path / name
    p.write_bytes(PNG_HEADER)
    return p


# ── strip_thinking ────────────────────────────────────────────────────────────

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

    def test_none_input_returns_empty_string(self):
        assert strip_thinking(None) == ""

    def test_empty_string_returns_empty_string(self):
        assert strip_thinking("") == ""

    def test_only_think_block_no_content_after(self):
        raw = "<think>thinking...</think>"
        assert strip_thinking(raw) == ""

    def test_multiple_think_blocks_only_first_stripped(self):
        # Only the outermost / first match is stripped
        raw = "<think>first</think>\nresult <think>second</think>"
        result = strip_thinking(raw)
        assert "first" not in result


# ── encode_image ──────────────────────────────────────────────────────────────

class TestEncodeImage:
    def test_png_media_type(self, tmp_path):
        img = _make_image(tmp_path, "wave.png")
        b64, media_type = encode_image(str(img))
        assert media_type == "image/png"
        assert len(b64) > 0

    def test_jpeg_media_type(self, tmp_path):
        img = tmp_path / "wave.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
        _, media_type = encode_image(str(img))
        assert media_type == "image/jpeg"

    def test_unknown_extension_defaults_to_png(self, tmp_path):
        img = tmp_path / "wave.tiff"
        img.write_bytes(b"\x00" * 16)
        _, media_type = encode_image(str(img))
        assert media_type == "image/png"

    def test_base64_is_valid(self, tmp_path):
        import base64
        img = _make_image(tmp_path)
        b64, _ = encode_image(str(img))
        decoded = base64.b64decode(b64)
        assert decoded == PNG_HEADER


# ── parse_waveform_image ──────────────────────────────────────────────────────

class TestParseWaveformImage:
    def test_clean_json_response(self, tmp_path):
        """VLM returns clean JSON directly."""
        img = _make_image(tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            json.dumps(DIGITAL_VLM_RESULT)
        )
        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "digital"
        assert len(result["signals"]) == 3
        assert result["confidence"] == 0.92

    def test_json_with_think_block(self, tmp_path):
        """VLM output contains a <think> block that should be stripped."""
        img = _make_image(tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            f"<think>analyzing waveform...</think>\n{json.dumps(DIGITAL_VLM_RESULT)}"
        )
        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "digital"

    def test_json_with_code_fence(self, tmp_path):
        """VLM output is wrapped in a ```json code fence."""
        img = _make_image(tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            f"```json\n{json.dumps(DIGITAL_VLM_RESULT)}\n```"
        )
        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "digital"

    def test_json_parse_error_fallback(self, tmp_path):
        """VLM returns invalid JSON → fallback to raw output."""
        img = _make_image(tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "Sorry, I cannot analyze this image."
        )
        result = parse_waveform_image(str(img), client=mock_client)
        assert result["confidence"] == 0.0
        assert "raw_vlm_output" in result

    def test_none_content_fallback(self, tmp_path):
        """VLM returns None content (e.g. API error) → fallback."""
        img = _make_image(tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(None)
        result = parse_waveform_image(str(img), client=mock_client)
        assert result["confidence"] == 0.0

    def test_analog_waveform_parsed(self, tmp_path):
        """Analog waveform result is returned intact."""
        img = _make_image(tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            json.dumps(ANALOG_VLM_RESULT)
        )
        result = parse_waveform_image(str(img), client=mock_client)
        assert result["waveform_type"] == "analog"
        assert result["analog_features"]["overshoot_pct"] == 8.5

    def test_low_confidence_result_still_returned(self, tmp_path):
        """Low confidence result is returned, not discarded."""
        low_conf = {**DIGITAL_VLM_RESULT, "confidence": 0.2, "signals": []}
        img = _make_image(tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            json.dumps(low_conf)
        )
        result = parse_waveform_image(str(img), client=mock_client)
        assert result["confidence"] == 0.2
        assert result["signals"] == []

    def test_request_uses_high_detail(self, tmp_path):
        """VLM request must use detail='high' for accurate analysis."""
        img = _make_image(tmp_path)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            json.dumps(DIGITAL_VLM_RESULT)
        )
        parse_waveform_image(str(img), client=mock_client)
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        image_content = call_kwargs["messages"][1]["content"][0]
        assert image_content["image_url"]["detail"] == "high"


# ── generate_assertion ────────────────────────────────────────────────────────

class TestGenerateAssertion:
    def test_returns_content_and_usage(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "```systemverilog\nassert property (@(posedge clk) req |-> ##[1:5] ack);\n```"
        )
        content, usage = generate_assertion(
            [{"role": "user", "content": "verify req-ack"}],
            client=mock_client,
        )
        assert "assert property" in content
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 200

    def test_system_prompt_is_injected(self):
        """System prompt from llm_system.md must always be the first message."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response("ok")
        generate_assertion(
            [{"role": "user", "content": "test"}], client=mock_client
        )
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert len(messages[0]["content"]) > 50  # non-trivial system prompt

    def test_conversation_history_appended_after_system(self):
        """User messages appear after the system prompt."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response("ok")
        user_msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        generate_assertion(user_msgs, client=mock_client)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1:] == user_msgs

    def test_empty_usage_handled(self):
        """Missing usage info returns empty dict, not an error."""
        mock_client = MagicMock()
        resp = _make_mock_response("content")
        resp.usage = None
        mock_client.chat.completions.create.return_value = resp
        _, usage = generate_assertion(
            [{"role": "user", "content": "test"}], client=mock_client
        )
        assert usage == {}


# ── AssertionSession ──────────────────────────────────────────────────────────

class TestAssertionSession:
    def test_set_waveform_returns_summary(self):
        session = AssertionSession()
        summary = session.set_waveform(DIGITAL_VLM_RESULT)
        assert "digital" in summary
        assert "clk" in summary
        assert "92%" in summary

    def test_set_waveform_low_confidence_note(self):
        low_conf = {**DIGITAL_VLM_RESULT, "confidence": 0.3, "parsing_notes": "blurry screenshot"}
        session = AssertionSession()
        summary = session.set_waveform(low_conf)
        assert "30%" in summary
        assert "blurry screenshot" in summary

    def test_set_waveform_analog_shows_features(self):
        session = AssertionSession()
        summary = session.set_waveform(ANALOG_VLM_RESULT)
        assert "analog" in summary
        assert "overshoot" in summary
        assert "ringing" in summary

    def test_set_waveform_no_signals_identified(self):
        no_signals = {**DIGITAL_VLM_RESULT, "signals": [], "confidence": 0.1}
        session = AssertionSession()
        summary = session.set_waveform(no_signals)
        assert "none identified" in summary.lower() or "10%" in summary

    def test_chat_first_turn_includes_vlm_context(self):
        """First chat turn must append the full VLM JSON to the user message."""
        session = AssertionSession()
        session.set_waveform(DIGITAL_VLM_RESULT)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response("ok")
        session.client = mock_client
        session.chat("Verify req-ack handshake")
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "Waveform Analysis" in user_msg["content"]
        assert "req-ack handshake" in user_msg["content"]  # user intent preserved

    def test_chat_second_turn_does_not_repeat_vlm_context(self):
        """VLM JSON should only appear in the first user message, not repeated."""
        session = AssertionSession()
        session.set_waveform(DIGITAL_VLM_RESULT)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response("first reply")
        session.client = mock_client
        session.chat("First question")

        mock_client.chat.completions.create.return_value = _make_mock_response("second reply")
        session.chat("Second question")

        # Second call: the last user message should NOT contain VLM context
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        last_user = [m for m in messages if m["role"] == "user"][-1]
        assert "Waveform Analysis" not in last_user["content"]
        assert last_user["content"] == "Second question"

    def test_chat_collects_sv_code_blocks(self):
        """SystemVerilog code blocks in LLM replies are auto-collected."""
        session = AssertionSession()
        session.set_waveform(DIGITAL_VLM_RESULT)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "Here is the assertion:\n"
            "```systemverilog\n"
            "assert property (@(posedge clk) req |-> ##[1:5] ack);\n"
            "```"
        )
        session.client = mock_client
        session.chat("Generate req-ack assertion")
        assert len(session.collected_code) == 1
        assert "assert property" in session.collected_code[0]

    def test_chat_collects_python_code_blocks(self):
        """Python code blocks are also collected."""
        session = AssertionSession()
        session.set_waveform(ANALOG_VLM_RESULT)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "```python\n"
            "assert overshoot < 0.1, f'Overshoot {overshoot:.1%} exceeds 10%'\n"
            "```"
        )
        session.client = mock_client
        session.chat("Check overshoot")
        assert len(session.collected_code) == 1

    def test_chat_multiple_code_blocks_all_collected(self):
        """Multiple code blocks in one reply are all collected."""
        session = AssertionSession()
        session.set_waveform(DIGITAL_VLM_RESULT)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "```systemverilog\nassert property (p1);\n```\n"
            "Also:\n"
            "```systemverilog\nassert property (p2);\n```"
        )
        session.client = mock_client
        session.chat("Give me two assertions")
        assert len(session.collected_code) == 2

    def test_chat_history_grows_correctly(self):
        """Each chat turn adds exactly one user + one assistant message."""
        session = AssertionSession()
        session.set_waveform(DIGITAL_VLM_RESULT)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response("reply")
        session.client = mock_client
        session.chat("First")
        session.chat("Second")
        assert len(session.history) == 4  # user, assistant, user, assistant
        assert session.history[0]["role"] == "user"
        assert session.history[1]["role"] == "assistant"

    def test_reset_clears_history_and_code(self):
        session = AssertionSession()
        session.history = [{"role": "user", "content": "test"}]
        session.collected_code = ["some code"]
        session.reset()
        assert session.history == []
        assert session.collected_code == []

    def test_reset_preserves_waveform_context(self):
        session = AssertionSession()
        session.set_waveform(DIGITAL_VLM_RESULT)
        session.reset()
        assert session.waveform_context is not None

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
        text = out.read_text()
        assert "Assertion 1" in text
        assert "Assertion 2" in text

    def test_save_assertions_auto_timestamp_path(self, tmp_path, monkeypatch):
        """Without explicit path, file is saved to output/ with timestamp."""
        import pipeline.session as sess_mod
        monkeypatch.setattr(sess_mod, "OUTPUT_DIR", tmp_path)
        session = AssertionSession()
        session.collected_code = ["assert p;"]
        count = session.save_assertions()
        assert count == 1
        sv_files = list(tmp_path.glob("assertions_*.sv"))
        assert len(sv_files) == 1


# ── SVA output format validation ──────────────────────────────────────────────

class TestSVAOutputFormat:
    """Validate that LLM-generated SVA has expected structural patterns."""

    VALID_SVA = (
        "property req_ack_handshake;\n"
        "  @(posedge clk) req |-> ##[1:5] ack;\n"
        "endproperty\n"
        "assert property (req_ack_handshake);"
    )

    def _session_with_response(self, response_text: str) -> AssertionSession:
        session = AssertionSession()
        session.set_waveform(DIGITAL_VLM_RESULT)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            f"```systemverilog\n{response_text}\n```"
        )
        session.client = mock_client
        return session

    def test_sva_contains_assert_keyword(self):
        session = self._session_with_response(self.VALID_SVA)
        session.chat("Verify req-ack")
        assert any("assert" in block for block in session.collected_code)

    def test_sva_contains_posedge_clock(self):
        session = self._session_with_response(self.VALID_SVA)
        session.chat("Verify req-ack")
        assert any("posedge" in block for block in session.collected_code)

    def test_analog_response_contains_meas_or_python(self):
        session = AssertionSession()
        session.set_waveform(ANALOG_VLM_RESULT)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            "```python\n"
            "assert vdd_overshoot < 0.1\n"
            "```"
        )
        session.client = mock_client
        session.chat("Check VDD overshoot")
        assert len(session.collected_code) == 1


# ── Integration tests (real image file, mocked API) ───────────────────────────

@pytest.mark.skipif(
    not (SAMPLE_WAVEFORMS / "digital_reqack.png").exists(),
    reason="Sample waveform not found",
)
class TestIntegration:
    """End-to-end pipeline tests using a real image file with mocked API calls."""

    def test_full_pipeline_digital(self):
        """Real image → mocked VLM → mocked LLM → assertion collected."""
        mock_client = MagicMock()
        # VLM call returns structured result
        mock_client.chat.completions.create.side_effect = [
            _make_mock_response(json.dumps(DIGITAL_VLM_RESULT)),   # VLM
            _make_mock_response(                                     # LLM
                "```systemverilog\n"
                "assert property (@(posedge clk) req |-> ##[1:5] ack);\n"
                "```"
            ),
        ]
        session = AssertionSession(client=mock_client)
        summary = session.load_image(str(SAMPLE_WAVEFORMS / "digital_reqack.png"))
        assert "digital" in summary
        assert "92%" in summary

        response = session.chat("Verify req-ack within 5 cycles")
        assert "assert property" in response
        assert len(session.collected_code) == 1

    def test_full_pipeline_save_output(self, tmp_path):
        """Full pipeline with file export."""
        import pipeline.session as sess_mod
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_mock_response(json.dumps(DIGITAL_VLM_RESULT)),
            _make_mock_response(
                "```systemverilog\nassert property (@(posedge clk) req |-> ##[1:5] ack);\n```"
            ),
        ]
        session = AssertionSession(client=mock_client)
        session.load_image(str(SAMPLE_WAVEFORMS / "digital_reqack.png"))
        session.chat("Verify handshake")

        out = tmp_path / "result.sv"
        count = session.save_assertions(str(out))
        assert count == 1
        assert "assert property" in out.read_text()

    def test_encode_image_with_real_file(self):
        """Real PNG file should encode without error."""
        import base64
        b64, media_type = encode_image(str(SAMPLE_WAVEFORMS / "digital_reqack.png"))
        assert media_type == "image/png"
        decoded = base64.b64decode(b64)
        assert decoded[:4] == b"\x89PNG"  # valid PNG magic bytes

    def test_vlm_request_includes_image_data(self):
        """VLM API call must include base64 image in the message content."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            json.dumps(DIGITAL_VLM_RESULT)
        )
        parse_waveform_image(
            str(SAMPLE_WAVEFORMS / "digital_reqack.png"), client=mock_client
        )
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_content = call_kwargs["messages"][1]["content"]
        image_part = next(p for p in user_content if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
