# Waveform Assertion Assistant

A screenshot-driven verification assertion generator for EDA workflows.

Upload a waveform screenshot and describe your verification intent in natural language. The system uses a VLM + LLM dual-model pipeline to automatically generate:
- **Digital waveforms** → SystemVerilog Assertions (SVA)
- **Analog waveforms** → HSPICE `.meas` + Python verification scripts

After each image upload the LLM automatically brainstorms verification checks mapped to common SVA / `.meas` templates, giving you a structured starting point before the conversation begins.

## Architecture

```
waveform_assertion/
├── src/
│   ├── pipeline/
│   │   ├── config.py         # Endpoint and model config (loaded from .env)
│   │   ├── vlm_parser.py     # VLM waveform image parsing → JSON
│   │   ├── llm_generator.py  # LLM assertion generation
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
├── output/                   # Generated assertions (timestamped)
├── examples/                 # Example waveform screenshots
├── Dockerfile
└── docker-compose.yml
```

## Models

| Role | Model | Notes |
|---|---|---|
| Waveform screenshot → JSON | `google/gemini-flash-1.5` | High-resolution image input |
| Assertion generation + chat | `anthropic/claude-3.5-haiku` | Multi-turn refinement |

Both models are accessed via [OpenRouter](https://openrouter.ai) using the OpenAI-compatible API.

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY
docker compose up
# Open http://localhost:7860
```

### Local

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY

# Web UI
PYTHONPATH=src python src/ui/app.py
# Open http://localhost:7860

# CLI mode
PYTHONPATH=src python -m pipeline.session path/to/waveform.png
```

## Usage

1. Open the web UI and upload a waveform screenshot (PNG / JPG / WebP, or paste with **Ctrl+V**)
2. The system parses the image and immediately brainstorms verification checks with template skeletons:
   - Digital → SVA templates (T1 req→ack, T3 data stability, T5 mutual exclusion, …)
   - Analog → `.meas` templates (M1 rise time, M3 propagation delay, M6 overshoot, …)
3. Describe your specific verification intent, for example:
   - `"Verify that ack asserts within 5 cycles after req goes high"`
   - `"Check that VDD overshoot stays below 10% during power-up"`
4. The system generates the corresponding SVA or HSPICE `.meas` script
5. Refine through multi-turn conversation; use **Export .sv** / **Export .py** to download

## Template Library

`llm_system.md` contains 8 SVA templates (T1–T8) and 8 `.meas` templates (M1–M8) that the LLM uses as the basis for both brainstorm suggestions and code generation.

| Tag | SVA Template | Tag | .meas Template |
|-----|-------------|-----|---------------|
| T1 | Req → Ack latency | M1 | Rise time (10%–90%) |
| T2 | No spurious ack | M2 | Fall time (90%–10%) |
| T3 | Data stability | M3 | Propagation delay |
| T4 | Pulse width | M4 | Clock period |
| T5 | Mutual exclusion | M5 | Settling time |
| T6 | Reset behavior | M6 | Overshoot / undershoot |
| T7 | No glitch | M7 | Setup / hold time |
| T8 | Eventually high | M8 | Average current / power |

## Output Examples

**Digital waveform → SVA (T1)**
```systemverilog
property p_req_ack;
  @(posedge CLK) disable iff (!RSTn)
  $rose(REQ) |-> ##[1:5] ACK;
endproperty
assert property (p_req_ack);
```

**Analog waveform → HSPICE .meas (M6)**
```spice
.meas tran VPEAK    MAX v(VDD) FROM=0ns TO=100ns
.meas tran VSTEADY  AVG v(VDD) FROM=80ns TO=100ns
.meas tran VOVSHOOT PARAM='(VPEAK-VSTEADY)/VSTEADY*100'
```

## Development

```bash
# Run all tests (mocked, no real API calls needed)
pytest tests/ -v

# Add test waveforms
cp your_waveform.png tests/sample_waveforms/
```
