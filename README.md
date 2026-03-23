# Waveform Assertion Assistant

A screenshot-driven verification assertion generator for EDA workflows.

Upload a waveform screenshot and describe your verification intent in natural language. The system uses a VLM + LLM dual-model pipeline to automatically generate:
- **Digital waveforms** → SystemVerilog Assertions (SVA)
- **Analog waveforms** → HSPICE `.meas` + Python verification scripts

## Architecture

```
waveform_assertion/
├── src/
│   ├── pipeline/
│   │   ├── config.py         # Endpoint and model config (loaded from .env)
│   │   ├── vlm_parser.py     # VLM waveform image parsing → JSON
│   │   ├── llm_generator.py  # LLM assertion generation
│   │   └── session.py        # Conversation state management + CLI
│   └── prompts/
│       ├── vlm_system.md     # VLM system prompt
│       └── llm_system.md     # LLM system prompt
├── tests/
│   ├── sample_waveforms/     # Test screenshots
│   └── test_pipeline.py
├── output/                   # Generated assertions (timestamped)
└── examples/                 # Example waveform screenshots
```

## Models

| Role | Model | Notes |
|---|---|---|
| Waveform screenshot → JSON | `google/gemini-flash-1.5` | High-resolution image input |
| Assertion generation + chat | `anthropic/claude-3.5-haiku` | Multi-turn refinement |

Both models are accessed via [OpenRouter](https://openrouter.ai) using the OpenAI-compatible API.

## Quick Start

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Configure API key**
```bash
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY
```

**3. Run**
```bash
# CLI mode
PYTHONPATH=src python -m pipeline.session path/to/waveform.png

# Run tests
pytest tests/ -v
```

## Usage

1. Provide a waveform screenshot (PNG / JPG / WebP)
2. Describe your verification intent in natural language, for example:
   - `"Verify that ack asserts within 5 cycles after req goes high"`
   - `"Check that VDD overshoot stays below 10% during power-up"`
3. The system generates the corresponding SVA or HSPICE `.meas` script
4. Refine through multi-turn conversation, then type `save` to export

## Output Examples

**Digital waveform → SVA**
```systemverilog
property req_ack_handshake;
  @(posedge clk) req |-> ##[1:5] ack;
endproperty
assert property (req_ack_handshake);
```

**Analog waveform → HSPICE .meas**
```spice
.meas tran overshoot_vdd MAX V(vdd) FROM=0ns TO=100ns
.meas tran settling_time TRIG V(vdd) VAL=0.9 TARG V(vdd) VAL=1.0
```

## Development

```bash
# Run all tests (mocked, no real API calls needed)
pytest tests/ -v

# Add test waveforms
cp your_waveform.png tests/sample_waveforms/
```
