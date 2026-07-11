"""genai client + model IDs, in ONE place.

VERIFY ON HACKATHON DAY: preview model names drift. First thing on arrival,
run `python -m common.client` to list models and confirm every ID below
resolves on the provisioned account. Override via env var if they differ.
"""

from __future__ import annotations

import os
from google import genai

# Auto-load the API key from a .env if present, so every entrypoint works
# without manually `source`-ing it. No-op if python-dotenv isn't installed.
try:
    from dotenv import load_dotenv
    load_dotenv()  # cwd/.env
    for _p in ("/home/colligo/.env", os.path.expanduser("~/.env")):
        if os.path.exists(_p):
            load_dotenv(_p)
except ImportError:
    pass

# --- Model IDs (override with env if the provisioned account differs) --------
MODEL_TEXT = os.environ.get("CK_MODEL_TEXT", "gemini-3.5-flash")
MODEL_IMAGE = os.environ.get("CK_MODEL_IMAGE", "gemini-3.1-flash-lite-image")
MODEL_VIDEO = os.environ.get("CK_MODEL_VIDEO", "gemini-omni-flash-preview")
MODEL_TTS = os.environ.get("CK_MODEL_TTS", "gemini-3.1-flash-tts-preview")

REQUIRED_MODELS = [MODEL_TEXT, MODEL_IMAGE, MODEL_VIDEO, MODEL_TTS]

_client = None


def get_client() -> "genai.Client":
    """Lazy singleton. Reads GEMINI_API_KEY from env (or google-genai default)."""
    global _client
    if _client is None:
        _client = genai.Client()  # picks up GEMINI_API_KEY
    return _client


def check_models() -> None:
    """Print available models and flag any REQUIRED_MODELS that don't resolve.

    Run this at T+0 on the provisioned account before building anything.
    """
    client = get_client()
    available = {m.name.split("/")[-1] for m in client.models.list()}
    print(f"{len(available)} models visible on this account.\n")
    for mid in REQUIRED_MODELS:
        mark = "OK " if mid in available else "!! MISSING"
        print(f"  [{mark}] {mid}")
    missing = [m for m in REQUIRED_MODELS if m not in available]
    if missing:
        print(f"\nMISSING: {missing}. Set CK_MODEL_* env vars to the correct IDs.")
    else:
        print("\nAll required models resolve.")


if __name__ == "__main__":
    check_models()
