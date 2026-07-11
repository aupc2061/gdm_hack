"""Omni Flash synthesis: SelectedFrame -> per-beat video clip.

Owner: Person 2 (you).

VERIFIED 2026-07-10 (out/probe): Omni image-to-video accepts EXACTLY ONE image
input. The combined FIRST_FRAME + IMAGE_REF_N call is REJECTED by the API:
    BadRequestError: Image-to-video does not support more than 1 image.
So we use the single-keyframe path only. The keyframe is already anchor-
conditioned from NB2 generation, so character consistency is preserved; any
extra prop/character guidance goes in motion_text, not as extra images.

AUDIO: Omni generates its OWN audio track natively (verified — ambient/SFX,
possibly music/voice). We rely on that by default for the demo (showcasing
Omni's multimodality at a GDM hackathon). We do NOT suppress it in the prompt.
Optional TTS narration (video/narrate.py) is a FALLBACK we can mix on top only
if Omni's native audio is poor — see stitch.build_final(narration=...).

CRITICAL: store=True on every call — required for redirect.py.
Duration is NOT controllable; [0-Xs] only choreographs content within the clip.
Observed: image_to_video ~36s wall-clock, ~5-10s output clip WITH audio.
"""

from __future__ import annotations

import base64
import os
from typing import List

from common.client import get_client, MODEL_VIDEO
from common.schema import SelectedFrame, BeatClip

# We keep only the framing rule (single continuous shot). We deliberately do NOT
# add "no dialogue/voiceover" — we want Omni's native audio for the demo.
SHOT_RULES = "Single continuous shot, no scene cuts. No text overlay."


def _save_video(interaction, path: str) -> None:
    part = interaction.output_video
    data = part.data
    if isinstance(data, str):
        data = base64.b64decode(data)
    with open(path, "wb") as f:
        f.write(data)


def _motion_prompt(fr: SelectedFrame) -> str:
    """Build the text prompt. Anchors are described in words (they can't be
    passed as extra images), then the framing rule is appended."""
    who = ""
    if fr.anchor_names:
        who = "Featuring the " + ", ".join(fr.anchor_names) + ". "
    return f"{who}{fr.motion_text}. {SHOT_RULES}"


def synth_beat(fr: SelectedFrame, out_dir: str) -> BeatClip:
    """Generate one beat's video from its keyframe. store=True. Returns BeatClip."""
    client = get_client()
    os.makedirs(out_dir, exist_ok=True)

    it = client.interactions.create(
        model=MODEL_VIDEO,
        input=[
            {"type": "image", "data": fr.selected_keyframe_b64, "mime_type": "image/png"},
            {"type": "text", "text": _motion_prompt(fr)},
        ],
        generation_config={"video_config": {"task": "image_to_video"}},
        store=True,  # REQUIRED for re-direction
        response_format={"type": "video", "aspect_ratio": "16:9"},
    )
    mp4 = os.path.join(out_dir, f"beat{fr.beat_id}.mp4")
    _save_video(it, mp4)
    print(f"  beat {fr.beat_id}: {mp4}  (interaction {it.id})")
    return BeatClip(beat_id=fr.beat_id, mp4_path=mp4, omni_interaction_id=it.id)


def synth_all(frames: List[SelectedFrame], out_dir: str) -> List[BeatClip]:
    """Sequential (avoid Omni rate limits). Returns BeatClips in beat order."""
    return [synth_beat(fr, out_dir) for fr in sorted(frames, key=lambda f: f.beat_id)]


# ---------------------------------------------------------------------------
# Latency / clip-length probe — run against one real keyframe.
# ---------------------------------------------------------------------------

def measure(keyframe_png: str, out_dir: str = "out/smoke") -> None:
    """Synthesize one clip and report wall-clock latency + ACTUAL clip length
    (uncontrollable — plan the reconcile around whatever this reports).

        python -m video.synth
    """
    import time
    from common.io import png_to_b64

    fr = SelectedFrame(
        beat_id=0,
        selected_keyframe_b64=png_to_b64(keyframe_png),
        anchor_b64s=[],
        anchor_names=["lion", "mouse"],
        motion_text="[0-5s] the lion slowly opens its eyes and lifts its head. Slow push-in.",
        duration_s=5.0,
        narration="",
    )
    t0 = time.time()
    clip = synth_beat(fr, out_dir)
    print(f"\nMEASURE: elapsed={time.time() - t0:.1f}s  file={clip.mp4_path}")
    try:
        from moviepy import VideoFileClip
        print(f"MEASURE: actual clip length = {VideoFileClip(clip.mp4_path).duration:.2f}s "
              f"(UNCONTROLLABLE — reconcile handles the mismatch)")
    except Exception as e:
        print(f"MEASURE: could not read clip length ({e})")


if __name__ == "__main__":
    measure("fixtures/beat0_keyframe.png")
