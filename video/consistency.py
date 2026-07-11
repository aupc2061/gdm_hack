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

class CharacterPrimitive(BaseModel):
    name: str
    must_have: str = Field(description="concrete, checkable visual attributes")


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
    """Attribute-level check of ONE frame against the primitive contract."""
    client = get_client()
    spec = prim.model_dump_json(indent=2)
    parts = [
        {"type": "text", "text": (
            "Check this video frame against the required primitives below. For EACH "
            "character, verify its `must_have` attributes are present exactly as "
            "described. Be strict and literal about attributes (tail shape, color, "
            "mane). Report per-attribute satisfied/not with what you actually saw.\n\n"
            f"PRIMITIVES:\n{spec}")},
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


def _fix_prompt(violations: List[AttrCheck]) -> str:
    """Turn violated attributes into a surgical re-direction instruction."""
    fixes = "; ".join(f"the {v.attribute} should be correct ({v.note})"
                      for v in violations)
    return (f"Fix these consistency issues: {fixes}. Match the required design "
            f"exactly. Keep everything else the same.")


def enforce(session: RedirectSession, prim: Primitives,
            max_rounds: int = MAX_ROUNDS) -> dict:
    """Check every beat's rendered clip against the primitives; auto re-direct
    violators; re-check; loop up to max_rounds. Bounded hard stop.

    Returns a report {beat_id: {"rounds": n, "resolved": bool, "final": [attrs]}}.
    """
    report = {}
    for beat_id in session.beat_ids:
        rounds = 0
        while rounds < max_rounds:
            clip = session.beats[beat_id]["cur_clip"]
            violations = check_beat(clip, prim)
            if not violations:
                print(f"  beat {beat_id}: consistent ✓")
                break
            attrs = [v.attribute for v in violations]
            print(f"  beat {beat_id}: violations {attrs} -> re-directing (round {rounds + 1})")
            session.edit(beat_id, _fix_prompt(violations), restitch=False)
            rounds += 1
        else:
            violations = check_beat(session.beats[beat_id]["cur_clip"], prim)
        report[beat_id] = {"rounds": rounds, "resolved": not violations,
                           "final": [v.attribute for v in violations]}
    short = session.restitch()
    print(f"\nEnforced short -> {short}")
    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Enforce JSON consistency primitives across a run.")
    ap.add_argument("--run", default="out/stage3")
    ap.add_argument("--primitives", help="path to a primitives JSON file")
    args = ap.parse_args()

    if args.primitives:
        prim = Primitives.model_validate_json(open(args.primitives).read())
    else:
        # demo default — in the real pipeline this is DERIVED from the anchor
        prim = Primitives(
            style="Amar Chitra Katha comic, bold ink outlines, flat colors",
            characters=[
                CharacterPrimitive(name="lion", must_have="large golden mane, tan body"),
                CharacterPrimitive(name="small animal", must_have="a small mouse with a thin hairless tail (NOT a bushy squirrel tail)"),
            ])
    session = RedirectSession(args.run)
    rep = enforce(session, prim)
    print(json.dumps(rep, indent=2))
