# Waveform Assertion Assistant

EDA 波形截圖驅動的驗證 assertion 自動生成工具。

工程師上傳波形截圖，以自然語言描述驗證意圖，系統透過 VLM + LLM 雙模型 pipeline 自動生成：
- **數位波形** → SystemVerilog Assertions (SVA)
- **類比波形** → HSPICE `.meas` + Python 驗證腳本

## 架構

```
waveform_assertion/
├── src/
│   ├── pipeline/
│   │   ├── config.py         # 端點與模型設定（從 .env 讀取）
│   │   ├── vlm_parser.py     # VLM 波形圖片解析 → JSON
│   │   ├── llm_generator.py  # LLM assertion 生成
│   │   └── session.py        # 對話狀態管理 + CLI
│   └── prompts/
│       ├── vlm_system.md     # VLM system prompt
│       └── llm_system.md     # LLM system prompt
├── tests/
│   ├── sample_waveforms/     # 測試用截圖
│   └── test_pipeline.py
├── output/                   # 生成的 assertion（含時間戳記）
└── examples/                 # 範例波形截圖
```

## 模型

| 用途 | 模型 | 說明 |
|---|---|---|
| 波形截圖解析 → JSON | `google/gemini-flash-1.5` | 支援高解析度圖片輸入 |
| Assertion 生成 + 對話 | `anthropic/claude-3.5-haiku` | 多輪對話精煉 |

兩者皆透過 [OpenRouter](https://openrouter.ai) 呼叫（OpenAI-compatible API）。

## 快速開始

**1. 安裝依賴**
```bash
pip install -r requirements.txt
```

**2. 設定 API Key**
```bash
cp .env.example .env
# 編輯 .env，填入 OPENROUTER_API_KEY
```

**3. 執行**
```bash
# CLI 模式
PYTHONPATH=src python -m pipeline.session path/to/waveform.png

# 執行測試
pytest tests/ -v
```

## 使用流程

1. 提供波形截圖（支援 PNG / JPG / WebP）
2. 以自然語言描述驗證意圖，例如：
   - `「驗證 req 拉高後，ack 必須在 5 個 cycle 內回應」`
   - `「確認 VDD 上電後 overshoot 不超過 10%」`
3. 系統輸出對應的 SVA 或 HSPICE `.meas` 腳本
4. 可多輪對話精煉，最後以 `save` 指令存檔

## 輸出範例

**數位波形 → SVA**
```systemverilog
property req_ack_handshake;
  @(posedge clk) req |-> ##[1:5] ack;
endproperty
assert property (req_ack_handshake);
```

**類比波形 → HSPICE .meas**
```spice
.meas tran overshoot_vdd MAX V(vdd) FROM=0ns TO=100ns
.meas tran settling_time TRIG V(vdd) VAL=0.9 TARG V(vdd) VAL=1.0
```

## 開發

```bash
# 執行所有測試（含 mock，不需要真實 API）
pytest tests/ -v

# 新增測試波形
cp your_waveform.png tests/sample_waveforms/
```
