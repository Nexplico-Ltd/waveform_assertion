"""
Tests for UI helper functions in src/ui/app.py.
No Gradio server required.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ui.app import _extract_code_blocks, _collect_from_history, _format_sv, _format_py


# ── _extract_code_blocks ──────────────────────────────────────────────────────

class TestExtractCodeBlocks:
    def test_single_sv_block(self):
        text = "```systemverilog\nassert property (p1);\n```"
        blocks = _extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0] == ("systemverilog", "assert property (p1);\n")

    def test_multiple_blocks(self):
        text = (
            "First:\n```systemverilog\nassert p1;\n```\n"
            "Second:\n```python\nassert x == 1\n```"
        )
        blocks = _extract_code_blocks(text)
        assert len(blocks) == 2

    def test_filter_by_language(self):
        text = (
            "```systemverilog\nassert p1;\n```\n"
            "```python\nassert x\n```"
        )
        sv_blocks = _extract_code_blocks(text, lang_filter="systemverilog")
        assert len(sv_blocks) == 1
        assert sv_blocks[0][0] == "systemverilog"

    def test_filter_case_insensitive(self):
        text = "```SystemVerilog\nassert p1;\n```"
        blocks = _extract_code_blocks(text, lang_filter="systemverilog")
        assert len(blocks) == 1

    def test_no_code_blocks_returns_empty(self):
        assert _extract_code_blocks("plain text with no code") == []

    def test_spice_block_extracted(self):
        text = "```spice\n.meas tran v_max MAX V(vdd)\n```"
        blocks = _extract_code_blocks(text, lang_filter="spice")
        assert len(blocks) == 1

    def test_empty_string_returns_empty(self):
        assert _extract_code_blocks("") == []


# ── _collect_from_history ─────────────────────────────────────────────────────

class TestCollectFromHistory:
    SV_RESPONSE = (
        "Here is the SVA:\n"
        "```systemverilog\nassert property (@(posedge clk) req |-> ##[1:5] ack);\n```"
    )

    def test_gradio6_dict_format(self):
        """Gradio 6 dict format: list of {role, content} dicts."""
        history = [
            {"role": "user", "content": "verify req-ack"},
            {"role": "assistant", "content": self.SV_RESPONSE},
        ]
        blocks = _collect_from_history(history, "systemverilog")
        assert len(blocks) == 1

    def test_legacy_list_format(self):
        """Legacy Gradio list-of-lists format: [[user_msg, bot_msg], ...]"""
        history = [["verify req-ack", self.SV_RESPONSE]]
        blocks = _collect_from_history(history, "systemverilog")
        assert len(blocks) == 1

    def test_user_messages_not_collected(self):
        """Code in user messages should not be collected."""
        history = [
            {"role": "user", "content": "```systemverilog\nsome code\n```"},
            {"role": "assistant", "content": "I see your code."},
        ]
        blocks = _collect_from_history(history, "systemverilog")
        assert len(blocks) == 0

    def test_none_assistant_content_skipped(self):
        """Streaming placeholder (None content) should not error."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None},
        ]
        blocks = _collect_from_history(history)
        assert blocks == []

    def test_multimodal_list_content(self):
        """Content as list (Gradio 6 multimodal) is handled safely."""
        history = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "```systemverilog\nassert p;\n```"},
            ]},
        ]
        blocks = _collect_from_history(history, "systemverilog")
        assert len(blocks) == 1

    def test_empty_history_returns_empty(self):
        assert _collect_from_history([]) == []

    def test_multiple_turns_all_collected(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "```systemverilog\nassert p1;\n```"},
            {"role": "user", "content": "more"},
            {"role": "assistant", "content": "```systemverilog\nassert p2;\n```"},
        ]
        blocks = _collect_from_history(history, "systemverilog")
        assert len(blocks) == 2

    def test_no_filter_returns_all_languages(self):
        history = [
            {"role": "assistant", "content": (
                "```systemverilog\nassert p;\n```\n"
                "```python\nassert x\n```"
            )},
        ]
        blocks = _collect_from_history(history)
        assert len(blocks) == 2


# ── _format_sv / _format_py ───────────────────────────────────────────────────

class TestFormatters:
    def test_format_sv_numbering(self):
        blocks = [("systemverilog", "assert p1;"), ("systemverilog", "assert p2;")]
        result = _format_sv(blocks)
        assert "Assertion 1" in result
        assert "Assertion 2" in result
        assert "assert p1;" in result

    def test_format_py_numbering(self):
        blocks = [("python", "x = 1"), ("python", "y = 2")]
        result = _format_py(blocks)
        assert "Script 1" in result
        assert "Script 2" in result

    def test_format_empty_list(self):
        assert _format_sv([]) == ""
        assert _format_py([]) == ""
