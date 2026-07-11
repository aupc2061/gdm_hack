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
import time
from typing import List, Optional

from common.client import get_client, MODEL_VIDEO
from common.schema import SelectedFrame, BeatClip

# We keep only the framing rule (single continuous shot). We deliberately do NOT
# add "no dialogue/voiceover" — we want Omni's native audio for the demo.
SHOT_RULES = "Single continuous shot, no scene cuts. No text overlay."


class VideoBlocked(Exception):
    """Omni refused a beat's prompt (content guardrail) after all retries.

    Guardrails are INTERMITTENT and phrasing-sensitive — a benign folk-tale beat
    ('lion holds the trembling mouse', 'trapped in a net') can trip the filter on
    one call and pass on the next. synth_all() catches this so ONE blocked beat
    doesn't kill the whole render (mirrors story/keyframes.py's ImageBlocked).
    """


def _is_guardrail(exc: Exception) -> bool:
    s = str(exc).lower()
    return ("guardrail" in s or "input blocked" in s or "blocked" in s
            or "prohibited" in s or "safety" in s)


def _save_video(interaction, path: str) -> None:
    part = interaction.output_video
    data = part.data
    if isinstance(data, str):
        data = base64.b64decode(data)
    with open(path, "wb") as f:
        f.write(data)


def extract_thoughts(interaction) -> str:
    """Pull the model's reasoning summary from an interaction's 'thought' steps.

    Verified: with thinking_level=high + thinking_summaries='auto', Omni returns
    a 'thought' step whose .summary describes the physics/lighting reasoning
    before rendering. Returns '' if thinking was off / none surfaced.
    """
    out = []
    for step in getattr(interaction, "steps", None) or []:
        if getattr(step, "type", None) == "thought" and getattr(step, "summary", None):
            items = step.summary if isinstance(step.summary, list) else [step.summary]
            for x in items:
                out.append(getattr(x, "text", str(x)))
    return "\n".join(out).strip()


# thinking is a PRE-BAKE enhancer: it surfaces demoable physics reasoning but
# ~1.8x latency (verified 64.5s vs 36s). Off by default; on for baked demo clips.
_THINK_CONFIG = {"thinking_level": "high", "thinking_summaries": "auto"}


def _motion_prompt(fr: SelectedFrame) -> str:
    """Build the text prompt. Anchors are described in words (they can't be
    passed as extra images), then the framing rule is appended."""
    who = ""
    if fr.anchor_names:
        who = "Featuring the " + ", ".join(fr.anchor_names) + ". "
    return f"{who}{fr.motion_text}. {SHOT_RULES}"


def synth_beat(fr: SelectedFrame, out_dir: str, think: bool = False,
               retries: int = 2) -> BeatClip:
    """Generate one beat's video from its keyframe. store=True. Returns BeatClip.

    think=True enables Omni's physics/lighting reasoning (thinking_level=high),
    captures the thought text to beat<N>.thought.txt. Slower (~1.8x) — use for
    pre-baked demo clips, not live generation.

    Guardrail blocks are INTERMITTENT — retry a few times; on persistent block
    raise VideoBlocked so the caller can skip this beat rather than crash.
    """
    client = get_client()
    os.makedirs(out_dir, exist_ok=True)

    gen_cfg = {"video_config": {"task": "image_to_video"}}
    if think:
        gen_cfg.update(_THINK_CONFIG)

    last_exc = None
    for attempt in range(retries + 1):
        try:
            it = client.interactions.create(
                model=MODEL_VIDEO,
                input=[
                    {"type": "image", "data": fr.selected_keyframe_b64, "mime_type": "image/png"},
                    {"type": "text", "text": _motion_prompt(fr)},
                ],
                generation_config=gen_cfg,
                store=True,  # REQUIRED for re-direction
                response_format={"type": "video", "aspect_ratio": "16:9"},
            )
            break
        except Exception as e:
            last_exc = e
            if not _is_guardrail(e):
                raise  # real error (auth/network) — don't mask it
            if attempt < retries:
                print(f"  beat {fr.beat_id}: guardrail block, retrying ({attempt + 1}/{retries})...")
                time.sleep(2)
    else:
        raise VideoBlocked(f"beat {fr.beat_id} blocked after {retries + 1} attempts: {str(last_exc)[:120]}")

    mp4 = os.path.join(out_dir, f"beat{fr.beat_id}.mp4")
    _save_video(it, mp4)

    if think:
        thought = extract_thoughts(it)
        if thought:
            with open(os.path.join(out_dir, f"beat{fr.beat_id}.thought.txt"), "w") as f:
                f.write(thought)
            print(f"  beat {fr.beat_id}: thought captured ({len(thought)} chars)")

    print(f"  beat {fr.beat_id}: {mp4}  (interaction {it.id})")
    return BeatClip(beat_id=fr.beat_id, mp4_path=mp4, omni_interaction_id=it.id)


def synth_all(frames: List[SelectedFrame], out_dir: str, think: bool = False) -> List[BeatClip]:
    """Sequential (avoid Omni rate limits). Returns BeatClips in beat order.

    A beat blocked by guardrails after retries is SKIPPED (logged), not fatal —
    one bad beat must not sink the whole render. Mirrors story/keyframes.py.
    Returns only the beats that succeeded (may be fewer than len(frames)).
    """
    clips = []
    for fr in sorted(frames, key=lambda f: f.beat_id):
        try:
            clips.append(synth_beat(fr, out_dir, think=think))
        except VideoBlocked as e:
            print(f"  !! {e} -> SKIPPING beat {fr.beat_id} (stitch will omit it)")
    return clips


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
