import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
VLM_MODEL: str = os.getenv("VLM_MODEL", "google/gemini-flash-1.5")
LLM_MODEL: str = os.getenv("LLM_MODEL", "anthropic/claude-3.5-haiku")


def get_client() -> OpenAI:
    """Return an OpenRouter-compatible OpenAI client (shared by VLM and LLM)."""
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not set. Please create a .env file.")
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": "https://waveform-assertion.local",
            "X-Title": "Waveform Assertion Assistant",
        },
    )
