"""Shared contract for the ChitraKatha pipeline.

FROZEN INTERFACE. Both story/ and video/ import from here and nothing else
crosses the folder boundary. The one object that travels story -> video is
`SelectedFrame` (serialized as fixtures/selected.json + PNG files).

Do not add fields without both owners agreeing — this is the seam.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# DIRECTOR output (internal to story/, but defined here so both sides can read
# a storyboard if needed for debugging)
# ---------------------------------------------------------------------------


class Beat(BaseModel):
    beat_id: int = Field(description="0-indexed beat number")
    subject: str = Field(description="Who/what is in frame")
    action: str = Field(description="What happens in this beat")
    setting: str = Field(description="Location / time / mood")
    camera: str = Field(description="Shot type + movement")
    motion: str = Field(description="Explicit motion for Omni, e.g. 'lion slowly wakes'")
    duration_s: float = Field(description="PACING HINT ONLY — not an API contract; Omni length is uncontrollable")
    narration: str = Field(description="English voiceover line for this beat")
    image_prompt: str = Field(description="Full NB2 prompt for the keyframe (built by Director)")


class CharacterRef(BaseModel):
    name: str = Field(description="Character/prop name, e.g. 'lion', 'mouse'")
    sheet_prompt: str = Field(description="NB2 prompt to generate this one anchor reference image")


class Storyboard(BaseModel):
    global_style: str = Field(description="One style spec applied to ALL beats (locked: Amar Chitra Katha comic)")
    characters: List[CharacterRef] = Field(description="One entry per character/prop needing an anchor")
    beats: List[Beat]


# ---------------------------------------------------------------------------
# CRITIC output (internal to story/)
# ---------------------------------------------------------------------------


class Verdict(BaseModel):
    prompt_adherence: int = Field(description="1-5: does the image match the beat's described scene?")
    style_consistency: int = Field(description="1-5: does it match the anchor's art style + the locked look?")
    identity_vs_anchor: int = Field(default=3, description="1-5: do the characters look exactly like their anchor references?")
    composition: int = Field(description="1-5: is the framing/staging clear and well-composed?")
    narrative_fit: int = Field(default=3, description="1-5: does it read as THIS story moment (right action/emotion)?")
    best_index: int = Field(description="Index of the best candidate")
    fix_prompt: str = Field(default="", description="Targeted edit instruction if best still below threshold, else empty")
    # NOTE: 'continuity' axis intentionally dropped — parallel fan-out has no
    # guaranteed prior selected frame to compare against at score time.
    # identity_vs_anchor + narrative_fit added for the keyframe reward loop
    # (GOAL.md): score on proxy rewards, iterate targeted edits to a threshold.


# ---------------------------------------------------------------------------
# THE SEAM: story/ -> video/
# ---------------------------------------------------------------------------


class SelectedFrame(BaseModel):
    """One per beat. Produced by story/ (Critic winner), consumed by video/.

    Serialization: `common.io.save_selected([...])` writes selected.json with
    b64 fields inlined, OR writes PNGs to disk and stores relative paths — see
    io.py. video/ only ever reads this object.
    """

    beat_id: int
    selected_keyframe_b64: str = Field(description="PNG base64 — the Critic's winning keyframe")
    anchor_b64s: List[str] = Field(description="Ordered PNGs -> become IMAGE_REF_0..N in Omni")
    anchor_names: List[str] = Field(default_factory=list, description="Parallel to anchor_b64s, e.g. ['lion','mouse'] — for prompt wiring")
    motion_text: str = Field(description="story/ concatenates: action + '. ' + camera + '. ' + motion")
    duration_s: float = Field(description="Pacing hint only")
    narration: str = Field(description="English narration line")


# ---------------------------------------------------------------------------
# SYNTH output (internal to video/)
# ---------------------------------------------------------------------------


class BeatClip(BaseModel):
    beat_id: int
    mp4_path: str = Field(description="Path to the rendered per-beat clip (video only, pre-narration)")
    omni_interaction_id: Optional[str] = Field(default=None, description="store=True interaction id — REQUIRED for re-direction")
    wav_path: Optional[str] = Field(default=None, description="Path to the TTS narration wav for this beat")
