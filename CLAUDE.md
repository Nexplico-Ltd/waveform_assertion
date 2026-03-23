# Waveform Assertion Assistant

Screenshot-driven verification assertion generator for EDA workflows.
Engineers upload waveform screenshots and describe their verification intent in natural language. The system uses a VLM + LLM dual-model pipeline to generate SVA (digital) or SPICE .meas + Python scripts (analog).

## Architecture

```
waveform_assertion/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── conftest.py
├── Dockerfile
├── docker-compose.yml
├── src/
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── config.py         # Endpoint / model config, loaded from .env
│   │   ├── vlm_parser.py     # VLM call + JSON parsing
│   │   ├── llm_generator.py  # LLM call + assertion generation
│   │   └── session.py        # Conversation state management + CLI
│   ├── ui/
│   │   └── app.py            # Gradio web UI
│   └── prompts/
│       ├── vlm_system.md     # VLM system prompt (JSON schema)
│       └── llm_system.md     # LLM system prompt + SVA/meas template library
├── tests/
│   ├── sample_waveforms/     # Test screenshots
│   ├── test_pipeline.py      # Pipeline unit + integration tests
│   └── test_ui_helpers.py    # UI helper function tests
├── examples/                 # Example waveform screenshots
└── output/                   # Generated assertion files (timestamped)
```

## Models

| Model | Role | Provider |
|---|---|---|
| `google/gemini-flash-1.5` | Waveform screenshot → structured JSON | OpenRouter |
| `anthropic/claude-3.5-haiku` | Assertion generation + conversation | OpenRouter |

Both use the OpenAI-compatible API via OpenRouter. Config is in `src/pipeline/config.py` (loaded from `.env`, never hardcoded).

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Web UI (http://localhost:7860)
PYTHONPATH=src python src/ui/app.py

# Docker (recommended for deployment)
docker compose up

# CLI mode
PYTHONPATH=src python -m pipeline.session path/to/waveform.png

# Run tests
pytest tests/ -v
```

## Output Format

- **Digital waveforms** → SystemVerilog Assertions (`.sv`)
- **Analog waveforms** → HSPICE `.meas` + Python verification script (`.py`)
- All generated outputs saved to `output/` with timestamps

## Code Conventions

- Python 3.11+, type hints throughout
- All API calls use the `openai` SDK (OpenAI-compatible)
- VLM output must be structured JSON; LLM handles reasoning and generation
- Prompt text lives in `prompts/`, never hardcoded in source files
- VLM `<think>...</think>` CoT blocks must be stripped before passing to LLM
- `llm_system.md` contains a template library (T1–T8 SVA, M1–M8 `.meas`); update it when adding new assertion patterns
- Auto-brainstorm runs after every image upload via Gradio `.then()` chain; it maps suggestions to named templates and shows filled-in skeleton code
- **All code, comments, docstrings, print statements, and documentation must be written in English. No other languages.**
