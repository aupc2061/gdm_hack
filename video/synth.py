"""Omni Flash synthesis: SelectedFrame -> per-beat video clip.

Owner: Person 2 (you). The riskiest module.

TWO paths:
  PRIMARY  (combined FIRST_FRAME + IMAGE_REF_N in one call) — web-doc-only, NO
           cookbook example. MUST pass smoke_test() on the provisioned account
           before you trust it.
  FALLBACK (plain image_to_video: keyframe + motion text) — cookbook-proven
           (Get_started_Omni code 28). The keyframe already carries the
           anchor-consistent character, so refs are redundant for consistency.

CRITICAL: store=True on every call — required for redirect.py to work.
Duration is NOT controllable; [0-Xs] only choreographs content, not length.
"""

from __future__ import annotations

import base64
import os
from typing import List

from common.client import get_client, MODEL_VIDEO
from common.schema import SelectedFrame, BeatClip

# Toggle after smoke_test(). If the combined call binds refs correctly -> True.
USE_COMBINED = True

SHOT_RULES = "Single continuous shot, no scene cuts. No dialogue or voiceover. No text overlay."


def _save_video(interaction, path: str) -> None:
    part = interaction.output_video
    data = part.data
    if isinstance(data, str):
        data = base64.b64decode(data)
    with open(path, "wb") as f:
        f.write(data)


def _combined_prompt(fr: SelectedFrame) -> str:
    """Build the [# Sources ...][# References ...] tagged prompt.

    Image1 = keyframe (FIRST_FRAME); Image2.. = anchors (IMAGE_REF_0..).
    """
    ref_tags = " ".join(f"<IMAGE_REF_{i}>@Image{i + 2}" for i in range(len(fr.anchor_b64s)))
    names = fr.anchor_names or [f"subject {i}" for i in range(len(fr.anchor_b64s))]
    subj_desc = "; ".join(f"<IMAGE_REF_{i}> is the {names[i]}" for i in range(len(names)))
    return (
        f"[# Sources <FIRST_FRAME>@Image1] [# References {ref_tags}] "
        f"{subj_desc}. {fr.motion_text}. "
        f"Use Image1 as the exact starting frame. {SHOT_RULES}"
    )


def synth_beat(fr: SelectedFrame, out_dir: str) -> BeatClip:
    """Generate one beat's video clip. store=True. Returns BeatClip with interaction id."""
    client = get_client()
    os.makedirs(out_dir, exist_ok=True)

    if USE_COMBINED and fr.anchor_b64s:
        parts = [{"type": "image", "data": fr.selected_keyframe_b64, "mime_type": "image/png"}]
        for ab in fr.anchor_b64s:
            parts.append({"type": "image", "data": ab, "mime_type": "image/png"})
        parts.append({"type": "text", "text": _combined_prompt(fr)})
    else:
        parts = [
            {"type": "image", "data": fr.selected_keyframe_b64, "mime_type": "image/png"},
            {"type": "text", "text": f"{fr.motion_text}. {SHOT_RULES}"},
        ]

    it = client.interactions.create(
        model=MODEL_VIDEO,
        input=parts,
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
# T+0 SMOKE TEST — run this FIRST on the provisioned account.
# ---------------------------------------------------------------------------

def smoke_test(keyframe_png: str, anchor_pngs: List[str], out_dir: str = "out/smoke") -> None:
    """Prove the combined FIRST_FRAME+IMAGE_REF call works AND measure latency+length.

        python -m video.synth  (edit the paths at the bottom first)

    Watch: does the output honor the start frame? are refs bound to the right
    subjects? how long did it take? how long is the clip? If refs don't bind ->
    set USE_COMBINED = False and rerun to confirm the fallback path.
    """
    import time
    from common.io import png_to_b64

    fr = SelectedFrame(
        beat_id=0,
        selected_keyframe_b64=png_to_b64(keyframe_png),
        anchor_b64s=[png_to_b64(p) for p in anchor_pngs],
        anchor_names=["lion", "mouse"][:len(anchor_pngs)],
        motion_text="[0-5s] the lion slowly opens its eyes and lifts its head. Slow push-in.",
        duration_s=5.0,
        narration="",
    )
    t0 = time.time()
    clip = synth_beat(fr, out_dir)
    dt = time.time() - t0
    print(f"\nSMOKE: combined={USE_COMBINED}  elapsed={dt:.1f}s  file={clip.mp4_path}")
    try:
        from moviepy.editor import VideoFileClip
        print(f"SMOKE: actual clip length = {VideoFileClip(clip.mp4_path).duration:.2f}s "
              f"(this is UNCONTROLLABLE — plan reconcile around it)")
    except Exception as e:
        print(f"SMOKE: could not read clip length ({e})")


if __name__ == "__main__":
    # EDIT THESE to real files on hackathon day, then: python -m video.synth
    smoke_test("fixtures/beat0_keyframe.png",
               ["fixtures/beat0_anchor0.png", "fixtures/beat0_anchor1.png"])
