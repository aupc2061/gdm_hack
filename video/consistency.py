"""Primitive-enforcement correction loop (video side).

Owner: Person 2. The novel closing half of the global/local primitives idea:
after beats are rendered, an agent samples frames, checks them against the
GLOBAL primitive contract, and AUTO re-directs any beat that violates it —
reusing the proven RedirectSession. Bounded, hard-stop.

VERIFIED 2026-07-10 gates (out/probe):
  - Holistic "same character?" critique FAILS — the model reasons at STYLE level
    and calls any same-style lion "the same character". Do NOT use that.
  - JSON per-ATTRIBUTE enforcement WORKS — asked "does the small animal have a
    thin hairless tail (not bushy)?", the critic correctly flagged a squirrel.
    Its reason string ("bushy tail, not thin") is directly usable as a fix prompt.

So enforcement checks CONCRETE ATTRIBUTES from a JSON primitive spec, not identity.
IMPORTANT: primitives should be DERIVED FROM THE ANCHOR, not hand-guessed, or you
get false mismatches (a hand-written 'grey mouse' fails a generated brown mouse).
"""

from __future__ import annotations

import base64
import json
import os
from typing import List, Optional

from pydantic import BaseModel, Field

from common.client import get_client, MODEL_TEXT
from video.redirect import RedirectSession

# Sampled frames per beat to judge (a few across the clip, cheap).
FRAMES_PER_BEAT = 2
MAX_ROUNDS = 2  # bounded correction loop; hard stop after this.


# ---------------------------------------------------------------------------
# Primitive contract (JSON). GLOBAL = persist across all beats; per-beat locals
# can be layered in later. Images (anchors) are referenced by path.
# ---------------------------------------------------------------------------

class Feature(BaseModel):
    """One typed, checkable IDENTITY attribute (Option A: structured, not free-text).

    Identity only — color/shape/markings that must stay constant. NOT pose,
    expression, or lighting (those legitimately vary per beat and caused false
    flags in the free-text version, e.g. 'furrowed-brow expression')."""
    feature: str = Field(description="attribute name, e.g. 'eye', 'beak', 'body color'")
    value: str = Field(description="the required concrete value, e.g. 'solid black beady eye'")


class CharacterPrimitive(BaseModel):
    name: str
    features: List[Feature] = Field(description="3-5 distinctive identity features")


class Primitives(BaseModel):
    style: str
    characters: List[CharacterPrimitive]


# ---------------------------------------------------------------------------
# Critic verdict (per-attribute — the shape the gate proved works)
# ---------------------------------------------------------------------------

class AttrCheck(BaseModel):
    attribute: str
    satisfied: bool
    note: str = Field(description="what was actually seen")


class FrameVerdict(BaseModel):
    checks: List[AttrCheck]
    all_satisfied: bool


def _b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def sample_frames(mp4_path: str, n: int = FRAMES_PER_BEAT) -> List[str]:
    """Save n evenly-spaced frames from a clip; return their paths."""
    from moviepy import VideoFileClip
    v = VideoFileClip(mp4_path)
    dur = v.duration
    stem = mp4_path.rsplit(".", 1)[0]
    paths = []
    for i in range(n):
        t = min(dur - 0.05, (i + 0.5) * dur / n)
        p = f"{stem}._frame{i}.png"
        v.save_frame(p, t=t)
        paths.append(p)
    v.close()
    return paths


def check_frame(frame_png: str, prim: Primitives) -> FrameVerdict:
    """Per-FIELD check of ONE frame against the typed primitive contract.

    Checks the art style + each character's identity features. Explicitly ignores
    pose/expression/lighting (they vary legitimately) and only flags a feature when
    it CLEARLY differs — avoids the free-text version's over-triggering."""
    client = get_client()
    spec = prim.model_dump_json(indent=2)
    parts = [
        {"type": "text", "text": (
            "Check this frame against the required contract below.\n"
            "- Verify the `style` matches (flat bold comic look — NOT 3D/Pixar/photoreal).\n"
            "- For each character, verify each identity `feature` value is present.\n"
            "RULES: judge IDENTITY only — ignore pose, expression, camera angle, and "
            "lighting (those vary per scene). Flag a feature as NOT satisfied ONLY if it "
            "CLEARLY differs from the required value. When in doubt, mark it satisfied.\n"
            "Report one check per feature (attribute = the feature name), plus one for style.\n\n"
            f"CONTRACT:\n{spec}")},
        {"type": "image", "data": _b64(frame_png), "mime_type": "image/png"},
    ]
    it = client.interactions.create(
        model=MODEL_TEXT, input=parts,
        response_format={"type": "text", "mime_type": "application/json",
                         "schema": FrameVerdict.model_json_schema()})
    return FrameVerdict.model_validate_json(it.output_text)


def check_beat(mp4_path: str, prim: Primitives) -> List[AttrCheck]:
    """Check a beat's sampled frames; return the list of VIOLATED attributes
    (deduped by attribute name). Empty list == beat is consistent."""
    violations = {}
    for fp in sample_frames(mp4_path):
        v = check_frame(fp, prim)
        for c in v.checks:
            if not c.satisfied:
                violations[c.attribute] = c  # last note wins; dedupe by attr
    return list(violations.values())


# ---------------------------------------------------------------------------
# Anchor-derived, per-beat primitives (fixes the two integration gaps):
#   (1) hand-written specs cause false mismatches -> DERIVE from the anchor image.
#   (2) global primitives false-flag beats where a character is absent -> scope
#       each beat's primitives to the characters actually present in that beat
#       (SelectedFrame.anchor_names carries this).
# ---------------------------------------------------------------------------

class _DerivedFeatures(BaseModel):
    features: List[Feature]


def _derive_features(anchor_b64: str, name: str) -> List[Feature]:
    """Typed derivation (Option A): turn an anchor image into 3-5 structured
    IDENTITY features. Structured (not a free-text sentence) so nothing is
    dropped and each field is independently checkable + fixable.

    Explicitly excludes pose/expression/lighting — the free-text version captured
    'furrowed-brow expression' as identity and then false-flagged every frame."""
    client = get_client()
    parts = [
        {"type": "text", "text": (
            f"This is the character reference for '{name}'. Extract its 3-5 MOST distinctive, "
            f"permanent IDENTITY features — the ones that must stay identical in every scene. "
            f"Each feature = a short name + its concrete value (e.g. feature='eye', "
            f"value='small solid-black beady eye'; feature='beak', value='medium grey-black beak'). "
            f"Include ONLY stable identity (color, markings, body shape, eye/beak/mane shape). "
            f"EXCLUDE pose, expression, mood, camera angle, background, and lighting.")},
        {"type": "image", "data": anchor_b64, "mime_type": "image/png"},
    ]
    it = client.interactions.create(
        model=MODEL_TEXT, input=parts,
        response_format={"type": "text", "mime_type": "application/json",
                         "schema": _DerivedFeatures.model_json_schema()})
    return _DerivedFeatures.model_validate_json(it.output_text).features


def derive_beat_primitives(frames, style: str) -> dict:
    """Build {beat_id: Primitives} scoped to the characters PRESENT in each beat,
    with typed identity features DERIVED from each anchor image (deduped per name)."""
    derived: dict = {}  # name -> List[Feature] (derive each anchor once)
    beat_prims = {}
    for fr in frames:
        chars = []
        for name, b64 in zip(fr.anchor_names, fr.anchor_b64s):
            if name not in derived:
                derived[name] = _derive_features(b64, name)
                feats = ", ".join(f"{f.feature}={f.value}" for f in derived[name])
                print(f"  derived primitive: {name} -> {feats}", flush=True)
            chars.append(CharacterPrimitive(name=name, features=derived[name]))
        beat_prims[fr.beat_id] = Primitives(style=style, characters=chars)
    return beat_prims


def _fix_prompt(violations: List[AttrCheck]) -> str:
    """Turn violated features into a surgical re-direction instruction.

    Includes an explicit STYLE-LOCK: the free-text version's fixes drifted the
    art into 3D/Pixar. We pin the flat comic look so a fix can't regress style."""
    fixes = "; ".join(f"{v.attribute}: {v.note}" for v in violations)
    return (
        f"Fix only these specific details: {fixes}. "
        f"Keep the SAME flat 2D Amar Chitra Katha comic art style — bold ink outlines, "
        f"flat colors, NOT 3D, NOT Pixar, NOT photorealistic. "
        f"Change nothing else — keep the composition, background, and all other elements the same."
    )


def enforce(session: RedirectSession, beat_prims: dict,
            max_rounds: int = MAX_ROUNDS) -> dict:
    """Check every beat's rendered clip against ITS per-beat primitives; auto
    re-direct violators; re-check; loop up to max_rounds. Bounded hard stop.

    beat_prims: {beat_id: Primitives} — per-beat scoped (see derive_beat_primitives),
    so a beat is only checked against characters actually present in it.
    Returns a report {beat_id: {"rounds": n, "resolved": bool, "final": [attrs]}}.
    """
    report = {}
    for beat_id in session.beat_ids:
        prim = beat_prims.get(beat_id)
        if prim is None or not prim.characters:
            report[beat_id] = {"rounds": 0, "resolved": True, "final": []}
            continue
        rounds = 0
        violations = check_beat(session.beats[beat_id]["cur_clip"], prim)
        while violations and rounds < max_rounds:
            attrs = [v.attribute for v in violations]
            print(f"  beat {beat_id}: violations {attrs} -> re-directing (round {rounds + 1})", flush=True)
            session.edit(beat_id, _fix_prompt(violations), restitch=False)
            rounds += 1
            violations = check_beat(session.beats[beat_id]["cur_clip"], prim)
        if not violations:
            print(f"  beat {beat_id}: consistent ✓ ({rounds} fix round(s))", flush=True)
        else:
            print(f"  beat {beat_id}: still off after {rounds} rounds: {[v.attribute for v in violations]}", flush=True)
        report[beat_id] = {"rounds": rounds, "resolved": not violations,
                           "final": [v.attribute for v in violations]}
    short = session.restitch()
    print(f"\nEnforced short -> {short}", flush=True)
    return report


def enforce_run(run_dir: str, selected_json: str, style: str = "Amar Chitra Katha comic, bold ink outlines, flat colors",
                max_rounds: int = MAX_ROUNDS) -> dict:
    """Pipeline entry: derive per-beat primitives from the story's anchors, then
    enforce them on an already-rendered run_dir (has interactions.json + beatN.mp4).

    This is the post-render consistency net wired into run_video.
    """
    from common.io import load_selected
    frames = load_selected(selected_json)
    print("[enforce] deriving per-beat primitives from anchors...")
    beat_prims = derive_beat_primitives(frames, style)
    session = RedirectSession(run_dir)
    print("[enforce] checking rendered beats against primitives...")
    return enforce(session, beat_prims, max_rounds=max_rounds)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Enforce anchor-derived consistency primitives on a rendered run.")
    ap.add_argument("--run", default="out/crow_video", help="rendered run dir (interactions.json + beatN.mp4)")
    ap.add_argument("--selected", default="out/crow_story/selected.json", help="the story's selected.json (for anchors)")
    ap.add_argument("--max-rounds", type=int, default=MAX_ROUNDS)
    args = ap.parse_args()
    rep = enforce_run(args.run, args.selected, max_rounds=args.max_rounds)
    print(json.dumps(rep, indent=2))
