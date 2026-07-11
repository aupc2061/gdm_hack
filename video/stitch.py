"""Assembly: per-beat Omni clips -> final short.

Owner: Person 2. moviepy 2.x API (from moviepy import; .with_audio/.with_duration).

DEFAULT PATH (Omni native audio): Omni clips already carry their own audio, so
we simply concatenate them. This is the demo default — showcase Omni's
multimodality rather than overriding it.

FALLBACK PATH (TTS narration on top): if Omni's native audio is poor, call
build_final(beat_clips, narrate=True). Then per beat we generate TTS narration
and mix/replace. Narration is never truncated; the video is freeze-padded and
audio is silence-padded to max(video, audio).
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
from moviepy import (VideoFileClip, AudioFileClip, AudioArrayClip, ImageClip,
                     CompositeAudioClip, concatenate_videoclips)
from common.schema import BeatClip


# ---------------------------------------------------------------------------
# DEFAULT: keep Omni's native audio, just concatenate.
# ---------------------------------------------------------------------------

def build_native(beat_clips: List[BeatClip], out_path: str = "out/chitrakatha.mp4") -> str:
    """Concatenate Omni clips as-is (each keeps its own native audio)."""
    clips = [VideoFileClip(bc.mp4_path)
             for bc in sorted(beat_clips, key=lambda b: b.beat_id)]
    final = concatenate_videoclips(clips)
    # audio_codec="aac" is REQUIRED for browser playback — moviepy defaults to
    # MP3-in-MP4, which browsers play silently (video only, no sound).
    final.write_videofile(out_path, fps=24, audio_codec="aac")
    for c in clips:
        c.close()
    final.close()
    return out_path


# ---------------------------------------------------------------------------
# FALLBACK helpers: TTS narration reconciliation (used only if narrate=True).
# ---------------------------------------------------------------------------

def _pad_audio_to(a: AudioFileClip, target: float):
    """Return audio silence-padded to `target` seconds (never truncates)."""
    if a.duration >= target:
        return a
    fps = a.fps or 44100
    arr = a.to_soundarray(fps=fps)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    need = int(round((target - a.duration) * fps))
    silence = np.zeros((need, arr.shape[1]), dtype=arr.dtype)
    return AudioArrayClip(np.vstack([arr, silence]), fps=fps)


def reconcile(mp4_path: str, wav_path: str, keep_native: bool = False,
              duck: float = 0.35):
    """Attach narration to a clip, freeze-padding video and silence-padding audio
    to max(video, audio).

    keep_native=True: mix narration OVER the clip's own Omni audio, with that bed
      DUCKED to `duck` volume (0.35 = 35%) so the story narration sits clearly on
      top of the ambient sound. keep_native=False: narration replaces the audio."""
    v = VideoFileClip(mp4_path)
    a = AudioFileClip(wav_path)
    dur = max(v.duration, a.duration)
    if v.duration < dur:
        last = v.get_frame(v.duration - 0.04)
        v = concatenate_videoclips([v, ImageClip(last, duration=dur - v.duration)])
    a = _pad_audio_to(a, dur)
    if keep_native and v.audio is not None:
        bed = v.audio.with_volume_scaled(duck)   # duck Omni's ambient under narration
        a = CompositeAudioClip([bed, a])
    return v.with_audio(a).with_duration(dur)


def build_final(beat_clips: List[BeatClip], out_path: str = "out/chitrakatha.mp4",
                narrate: bool = False, keep_native: bool = False) -> str:
    """Default: build_native (Omni audio). If narrate=True, reconcile TTS per beat.

    When narrate=True, each BeatClip.wav_path must be set (run video/narrate.py).
    keep_native=True mixes TTS over Omni's audio instead of replacing it.
    """
    if not narrate:
        return build_native(beat_clips, out_path)

    clips = []
    for bc in sorted(beat_clips, key=lambda b: b.beat_id):
        if bc.wav_path is None:
            raise ValueError(f"beat {bc.beat_id} has no narration wav — set BeatClip.wav_path first")
        clips.append(reconcile(bc.mp4_path, bc.wav_path, keep_native=keep_native))
    final = concatenate_videoclips(clips)
    # audio_codec="aac" is REQUIRED for browser playback — moviepy defaults to
    # MP3-in-MP4, which browsers play silently (video only, no sound).
    final.write_videofile(out_path, fps=24, audio_codec="aac")
    for c in clips:
        c.close()
    final.close()
    return out_path
