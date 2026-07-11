"""Critic agent: score candidates, pick best, bounded single-regen.

Owner: Person 1. The honest inference-time verifier — best-of-N, not MCTS.

Regen rule (HARD STOP): if BOTH candidates score < THRESHOLD on ANY axis,
issue exactly ONE targeted regen for that beat, then pick best-of-existing.
No further loop — caps worst case at 2x per beat.
"""

from __future__ import annotations

from typing import Dict, List

from common.client import get_client, MODEL_TEXT
from common.schema import Storyboard, Beat, Verdict
from story.anchors import gen_image

THRESHOLD = 3  # regen if either candidate scores < 3/5 on any axis. Tune live.


def critique(candidates_b64: List[str], anchor_b64s: List[str], beat: Beat) -> Verdict:
    client = get_client()
    parts = [{"type": "text", "text": (
        f"The first {len(anchor_b64s)} image(s) are the character/style ANCHORS. The remaining "
        f"images are candidate keyframes for this beat: {beat.action} ({beat.setting}). "
        f"Score EACH candidate 1-5 on prompt_adherence, style_consistency (vs anchors), composition. "
        f"Return best_index (into the candidates only, 0-based) and a fix_prompt ONLY if the best "
        f"candidate still needs work, else empty."
    )}]
    for a in anchor_b64s:
        parts.append({"type": "image", "data": a, "mime_type": "image/png"})
    for c in candidates_b64:
        parts.append({"type": "image", "data": c, "mime_type": "image/png"})
    it = client.interactions.create(
        model=MODEL_TEXT,
        input=parts,
        response_format={"type": "text", "mime_type": "application/json",
                         "schema": Verdict.model_json_schema()},
    )
    return Verdict.model_validate_json(it.output_text)


def _below_threshold(v: Verdict) -> bool:
    return min(v.prompt_adherence, v.style_consistency, v.composition) < THRESHOLD


def select_best(beat: Beat, board: Storyboard, candidates_b64: List[str],
                anchor_b64s: List[str]) -> str:
    """Score, and if both weak do ONE regen. Returns the winning keyframe b64."""
    v = critique(candidates_b64, anchor_b64s, beat)
    if _below_threshold(v) and v.fix_prompt:
        print(f"  beat {beat.beat_id}: below threshold -> 1 regen ({v.fix_prompt[:50]}...)")
        prompt = f"{beat.image_prompt}. {v.fix_prompt}. Style: {board.global_style}. Keep characters identical to the references."
        regen = gen_image(prompt, refs=anchor_b64s)
        candidates_b64 = candidates_b64 + [regen]
        v = critique(candidates_b64, anchor_b64s, beat)  # re-score; HARD STOP after this
    idx = max(0, min(v.best_index, len(candidates_b64) - 1))
    return candidates_b64[idx]
