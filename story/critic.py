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
from story.style import style_clause

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
        prompt = f"{beat.image_prompt}. {v.fix_prompt}. {style_clause()} Keep characters identical to the references."
        regen = gen_image(prompt, refs=anchor_b64s)
        candidates_b64 = candidates_b64 + [regen]
        v = critique(candidates_b64, anchor_b64s, beat)  # re-score; HARD STOP after this
    idx = max(0, min(v.best_index, len(candidates_b64) - 1))
    return candidates_b64[idx]


# ---------------------------------------------------------------------------
# GLOBAL consistency pass — judges all winners TOGETHER (not per-beat isolation)
# ---------------------------------------------------------------------------


def _global_outlier_index(winners_b64: List[str]) -> tuple[int, str]:
    """Show all winners at once; ask which ONE frame breaks visual coherence.

    Per-beat selection is blind to the other beats, so the chosen set can drift
    in palette/lighting/border even when each frame is individually fine. This
    pass looks across the whole set and names the single worst outlier + why.
    Returns (index, reason). index == -1 means the set is coherent.
    """
    client = get_client()
    parts = [{"type": "text", "text": (
        f"These {len(winners_b64)} images are consecutive frames of ONE animated short, "
        f"in order. They must look like a single coherent picture-book: same art style, "
        f"same line weight, same overall palette and lighting, no stray captions or borders. "
        f"Identify the SINGLE frame that most breaks visual coherence with the rest. "
        f'Respond as JSON: {{"outlier_index": <0-based int, or -1 if all coherent>, '
        f'"reason": "<short, e.g. too dark / has a border / different line style>"}}.'
    )}]
    for w in winners_b64:
        parts.append({"type": "image", "data": w, "mime_type": "image/png"})
    it = client.interactions.create(
        model=MODEL_TEXT,
        input=parts,
        response_format={"type": "text", "mime_type": "application/json", "schema": {
            "type": "object",
            "properties": {
                "outlier_index": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["outlier_index", "reason"],
        }},
    )
    import json
    d = json.loads(it.output_text)
    return int(d.get("outlier_index", -1)), str(d.get("reason", ""))


def harmonize(beats: List[Beat], winners_b64: List[str],
              anchors_per_beat: List[List[str]], max_fixes: int = 1) -> List[str]:
    """Run the global judge; regen up to `max_fixes` outliers to match the set.

    Bounded (default 1 fix) to stay demo-safe. Returns the harmonized winners.
    The regen is conditioned on the OTHER frames' shared look via the reason.
    """
    winners = list(winners_b64)
    for _ in range(max_fixes):
        idx, reason = _global_outlier_index(winners)
        if idx < 0 or idx >= len(winners):
            print("  global consistency: set is coherent, no fix needed")
            break
        beat = beats[idx]
        print(f"  global consistency: beat {beat.beat_id} is the outlier ({reason}) -> regen to match")
        prompt = (
            f"{beat.image_prompt}. {style_clause()} "
            f"Match the shared look of the other frames in this sequence; "
            f"specifically fix: {reason}. Keep characters identical to the references."
        )
        try:
            winners[idx] = gen_image(prompt, refs=anchors_per_beat[idx])
        except Exception as e:
            print(f"  global consistency: regen failed ({e}); keeping original")
            break
    return winners
