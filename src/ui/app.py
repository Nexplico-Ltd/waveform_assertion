"""
Gradio web UI for Waveform Assertion Assistant.

Layout:
  Top row  : waveform image upload (left) | chat window (right)
  Bottom   : collected assertions panel with .sv / .py export
"""

import re
import sys
import tempfile
from pathlib import Path

import gradio as gr

# Allow running as: PYTHONPATH=src python src/ui/app.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.session import AssertionSession


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_code_blocks(text: str, lang_filter: str | None = None) -> list[tuple[str, str]]:
    """Return (language, code) pairs found in markdown text."""
    blocks = re.findall(r"```(\w+)\n(.*?)```", text, re.DOTALL)
    if lang_filter:
        blocks = [(l, c) for l, c in blocks if l.lower() == lang_filter.lower()]
    return blocks


def _collect_from_history(
    history: list[list], lang_filter: str | None = None
) -> list[tuple[str, str]]:
    """Collect all code blocks from chatbot history."""
    blocks = []
    for _, assistant_msg in history:
        if assistant_msg:
            blocks.extend(_extract_code_blocks(assistant_msg, lang_filter))
    return blocks


def _format_sv(blocks: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"// === Assertion {i + 1} ===\n{code}" for i, (_, code) in enumerate(blocks)
    )


def _format_py(blocks: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"# === Script {i + 1} ===\n{code}" for i, (_, code) in enumerate(blocks)
    )


def _refresh_assertion_panels(history: list[list]) -> tuple[str, str]:
    sv = _format_sv(_collect_from_history(history, "systemverilog"))
    py = _format_py(
        _collect_from_history(history, "python")
        + _collect_from_history(history, "spice")
    )
    return sv, py


# ── UI ────────────────────────────────────────────────────────────────────────

def build_ui() -> gr.Blocks:
    with gr.Blocks(
        title="Waveform Assertion Assistant",
        theme=gr.themes.Soft(),
        css=".chatbot-wrap .message { font-size: 14px; }",
    ) as demo:

        session_state: gr.State = gr.State(None)

        gr.Markdown("# Waveform Assertion Assistant")
        gr.Markdown(
            "Upload a waveform screenshot (drag & drop or paste with **Ctrl+V**), "
            "then describe what you want to verify."
        )

        # ── Top row ───────────────────────────────────────────────────────────
        with gr.Row(equal_height=False):

            # Left: image + VLM summary
            with gr.Column(scale=1, min_width=320):
                image_input = gr.Image(
                    type="filepath",
                    label="Waveform Screenshot",
                    height=280,
                    sources=["upload", "clipboard"],
                )
                vlm_status = gr.Markdown("_Upload a waveform screenshot to begin._")

            # Right: chat
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    label="Conversation",
                    height=450,
                    show_copy_button=True,
                    render_markdown=True,
                    bubble_full_width=False,
                )
                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="Describe what you want to verify...",
                        label="",
                        scale=5,
                        autofocus=True,
                        lines=1,
                    )
                    send_btn = gr.Button("Send", variant="primary", scale=1, min_width=80)

        # ── Assertion panel ───────────────────────────────────────────────────
        with gr.Accordion("Collected Assertions", open=True):
            with gr.Row():
                sv_display = gr.Code(
                    language="verilog",
                    label="SystemVerilog Assertions (.sv)",
                    interactive=False,
                    lines=12,
                )
                py_display = gr.Code(
                    language="python",
                    label="Python / HSPICE Scripts (.py)",
                    interactive=False,
                    lines=12,
                )
            with gr.Row():
                export_sv_btn = gr.Button("Export .sv", variant="secondary")
                export_py_btn = gr.Button("Export .py", variant="secondary")
                clear_btn = gr.Button("Clear Session", variant="stop")
            export_file = gr.File(label="Download", visible=False)

        # ── Event handlers ────────────────────────────────────────────────────

        def on_image_upload(
            image_path: str | None, session: AssertionSession | None
        ) -> tuple:
            if not image_path:
                return session, "_Upload a waveform screenshot to begin._"
            if session is None:
                session = AssertionSession()
            try:
                summary = session.load_image(image_path)
                return session, summary
            except Exception as e:
                return session, f"**Error parsing waveform:** {e}"

        def on_send(
            user_msg: str,
            history: list[list],
            session: AssertionSession | None,
        ):
            if not user_msg.strip():
                yield history, "", session, "", ""
                return

            if session is None:
                session = AssertionSession()

            history = (history or []) + [[user_msg, None]]
            yield history, "", session, "", ""

            try:
                response = session.chat(user_msg)
            except Exception as e:
                response = f"**Error:** {e}"

            history[-1][1] = response
            sv, py = _refresh_assertion_panels(history)
            yield history, "", session, sv, py

        def on_export_sv(history: list[list]):
            blocks = _collect_from_history(history, "systemverilog")
            if not blocks:
                return gr.File(visible=False)
            content = _format_sv(blocks)
            tmp = tempfile.NamedTemporaryFile(
                suffix=".sv", delete=False, mode="w", encoding="utf-8"
            )
            tmp.write(content)
            tmp.close()
            return gr.File(value=tmp.name, visible=True)

        def on_export_py(history: list[list]):
            blocks = (
                _collect_from_history(history, "python")
                + _collect_from_history(history, "spice")
            )
            if not blocks:
                return gr.File(visible=False)
            content = _format_py(blocks)
            tmp = tempfile.NamedTemporaryFile(
                suffix=".py", delete=False, mode="w", encoding="utf-8"
            )
            tmp.write(content)
            tmp.close()
            return gr.File(value=tmp.name, visible=True)

        def on_clear(session: AssertionSession | None):
            if session:
                session.reset()
                session.waveform_context = None
            return (
                None,
                [],
                "_Upload a waveform screenshot to begin._",
                "",
                "",
                gr.File(visible=False),
            )

        # ── Wire events ───────────────────────────────────────────────────────

        image_input.upload(
            on_image_upload,
            inputs=[image_input, session_state],
            outputs=[session_state, vlm_status],
        )

        for trigger in (send_btn.click, msg_input.submit):
            trigger(
                on_send,
                inputs=[msg_input, chatbot, session_state],
                outputs=[chatbot, msg_input, session_state, sv_display, py_display],
            )

        export_sv_btn.click(on_export_sv, inputs=[chatbot], outputs=[export_file])
        export_py_btn.click(on_export_py, inputs=[chatbot], outputs=[export_file])
        clear_btn.click(
            on_clear,
            inputs=[session_state],
            outputs=[session_state, chatbot, vlm_status, sv_display, py_display, export_file],
        )

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(server_port=7860, show_error=True)
