# Waveform Assertion Assistant

EDA 波形截圖驅動的驗證 assertion 自動生成工具。
工程師上傳波形截圖，以自然語言描述驗證意圖，系統透過 VLM + LLM 雙模型 pipeline 生成 SVA（數位）或 SPICE .meas + Python 腳本（類比）。

## 架構

```
waveform_assertion/
├── CLAUDE.md
├── requirements.txt
├── pipeline/
│   ├── vlm_parser.py       # Qwen3-VL-30B 波形視覺解析
│   ├── llm_generator.py    # gpt-oss-120b assertion 生成 + 對話
│   └── session.py          # 對話狀態管理
├── ui/
│   └── app.py              # Gradio web UI（截圖貼上 + 對話）
├── prompts/
│   ├── vlm_system.md       # VLM 解析 prompt
│   └── llm_system.md       # LLM assertion 生成 prompt
├── tests/
│   ├── sample_waveforms/   # 測試用截圖
│   └── test_pipeline.py
└── output/                 # 生成的 assertion 存檔
```

## 模型端點

| 模型 | 用途 | Endpoint |
|---|---|---|
| Qwen3-VL-30B-A3B-Thinking | 波形截圖解析 → JSON | `http://localhost:8000/v1` |
| gpt-oss-120b | Assertion 生成 + 對話 | `http://localhost:8001/v1` |

兩個都是本地 vLLM，OpenAI-compatible API。
設定在 `pipeline/config.py`（從 `.env` 讀取，不 hardcode）。

## 開發指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 啟動 web UI
python ui/app.py

# CLI 模式
python -m pipeline.session --image path/to/waveform.png

# 執行測試
pytest tests/ -v
```

## 輸出格式規範

- **數位波形** → SystemVerilog Assertions (`.sv`)
- **類比波形** → HSPICE `.meas` + Python 驗證腳本 (`.py`)
- 所有生成結果存入 `output/` 並附時間戳記

## 程式碼規範

- Python 3.11+，使用 type hints
- 所有 API 呼叫用 `openai` SDK（OpenAI-compatible）
- VLM 輸出必須是 structured JSON，LLM 負責推理與生成
- Prompt 文字獨立存放於 `prompts/`，不 hardcode 在程式碼中
- IMPORTANT: VLM 的 Thinking CoT（`<think>...</think>`）必須在送給 LLM 前剝離

## 目前狀態

剛建立專案，從 `waveform_pipeline.py`（單檔原型）重構成模組化結構。
原型已驗證雙模型 pipeline 流程可行。
