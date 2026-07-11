"""Assembly: per-beat clips + narration -> final short.

Owner: Person 2. Reconcile rule (authoritative): Omni clip length is
uncontrollable and our clips are real motion (not static), so:
  - NEVER truncate narration
  - NEVER time-stretch video
  - pad the shorter to max(video, audio) by FREEZING the last video frame
"""

from __future__ import annotations

from typing import List

from moviepy.editor import (VideoFileClip, AudioFileClip, ImageClip,
                            concatenate_videoclips)
from common.schema import BeatClip
from video.narrate import narrate


def reconcile(mp4_path: str, wav_path: str):
    """Return a MoviePy clip where narration plays in full and video is freeze-padded."""
    v = VideoFileClip(mp4_path)
    a = AudioFileClip(wav_path)
    dur = max(v.duration, a.duration)
    if v.duration < dur:
        pad = ImageClip(v.get_frame(v.duration - 0.04)).set_duration(dur - v.duration)
        v = concatenate_videoclips([v, pad])
    return v.set_audio(a).set_duration(dur)


def build_final(beat_clips: List[BeatClip], out_path: str = "out/chitrakatha.mp4") -> str:
    """Narrate each beat (if not already), reconcile, concatenate. Returns out_path."""
    clips = []
    for bc in sorted(beat_clips, key=lambda b: b.beat_id):
        wav = bc.wav_path
        if wav is None:
            raise ValueError(f"beat {bc.beat_id} has no narration wav — set BeatClip.wav_path first")
        clips.append(reconcile(bc.mp4_path, wav))
    final = concatenate_videoclips(clips)
    final.write_videofile(out_path, fps=24)
    for c in clips:
        c.close()
    final.close()
    return out_path
