"""TTS narration: narration text -> wav.

Owner: Person 2.

VERIFIED 2026-07-10 (out/probe): TTS uses client.models.generate_content, NOT
interactions.create. The interactions form is rejected. Audio PCM bytes are at
    response.candidates[0].content.parts[0].inline_data.data
(24kHz, mono, 16-bit). Language is auto-detected from the text (a Hindi line
would just work — future multi-language).
"""

from __future__ import annotations

import contextlib
import os
import wave

from google.genai import types
from common.client import get_client, MODEL_TTS

VOICE = "Kore"


@contextlib.contextmanager
def _wave_file(path: str, ch: int = 1, rate: int = 24000, sw: int = 2):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(sw)
        wf.setframerate(rate)
        yield wf


def _extract_pcm(response) -> bytes | None:
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return inline.data
    return None


def narrate(text: str, out_path: str, voice: str = VOICE) -> str:
    """Generate narration wav. Returns out_path."""
    client = get_client()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    response = client.models.generate_content(
        model=MODEL_TTS,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        ),
    )
    pcm = _extract_pcm(response)
    if pcm is None:
        raise RuntimeError("No audio returned from TTS response")
    with _wave_file(out_path) as wf:
        wf.writeframes(pcm)
    return out_path


if __name__ == "__main__":
    p = narrate("Once, a mighty lion lay sleeping in the forest.", "out/smoke/narr0.wav")
    print(f"wrote {p}")
