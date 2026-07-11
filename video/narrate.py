"""TTS narration: narration text -> wav.

Owner: Person 2. Cookbook-confirmed shape (Get_started_TTS): config with
response_modalities=["AUDIO"] + typed SpeechConfig. Audio bytes live in
interaction.steps[].content[].inline_data. Language auto-detected from text
(so a Hindi narration line would just work — future multi-language).
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


def _extract_pcm(interaction) -> bytes | None:
    for step in interaction.steps:
        if step.type == "model_output":
            for c in step.content:
                if getattr(c, "inline_data", None):
                    return c.inline_data.data
    return None


def narrate(text: str, out_path: str, voice: str = VOICE) -> str:
    """Generate narration wav. Returns out_path."""
    client = get_client()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    it = client.interactions.create(
        model=MODEL_TTS,
        input=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        ),
    )
    pcm = _extract_pcm(it)
    if pcm is None:
        raise RuntimeError("No audio returned from TTS interaction")
    with _wave_file(out_path) as wf:
        wf.writeframes(pcm)
    return out_path


if __name__ == "__main__":
    p = narrate("Once, a mighty lion lay sleeping in the forest.", "out/smoke/narr0.wav")
    print(f"wrote {p}")
