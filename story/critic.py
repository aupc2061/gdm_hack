"""Critic agent: verifier-guided keyframe reward loop (GOAL.md centerpiece).

Owner: Person 1. The honest inference-time verifier — greedy search over
targeted image edits, NOT blind best-of-N and NOT MCTS.

Reward loop (per beat), the novelty core:
  seed = best of the fan-out candidates (one multi-candidate critique)
  repeat up to MAX_ITERS (budget K):
      score the frame on 5 proxy-reward axes (1-5 each)
      if min(axes) >= THRESHOLD:  break         # earned it
      apply ONE targeted NB2 edit to the SAME frame (not a fresh regen)
  return the highest-total-reward frame seen (best-seen), plus the full
  score trajectory (the live demo wow).

Bounds (demo-safe): hard cap K, always keep best-seen, log every iteration.
Output is still a keyframe b64 — the common/schema seam does not change.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from common.client import get_client, MODEL_TEXT
from common.schema import Storyboard, Beat, Verdict
from story.anchors import gen_image
from story.style import style_clause

THRESHOLD = 4      # a frame is "earned" when every reward axis is >= this. Tune live.
MAX_ITERS = 3      # budget K: max targeted edits per beat after the seed. Hard cap.

# The proxy-reward axes the loop optimizes. reward = min(axes); total = sum(axes).
REWARD_AXES = ("prompt_adherence", "style_consistency", "identity_vs_anchor",
               "composition", "narrative_fit")


def _reward(v: Verdict) -> int:
    """The scalar reward: the weakest axis (a frame is only as good as its worst flaw)."""
    return min(getattr(v, a) for a in REWARD_AXES)


def _total(v: Verdict) -> int:
    """Tie-breaker for best-seen selection across iterations."""
    return sum(getattr(v, a) for a in REWARD_AXES)


def _scores_dict(v: Verdict) -> Dict[str, int]:
    return {a: getattr(v, a) for a in REWARD_AXES}


def critique(candidates_b64: List[str], anchor_b64s: List[str], beat: Beat) -> Verdict:
    """Score N candidates together; used to pick the SEED frame for the loop.

    Scores are for the candidate at best_index. fix_prompt = a targeted edit
    for that best candidate if it still falls short, else empty.
    """
    client = get_client()
    parts = [{"type": "text", "text": (
        f"The first {len(anchor_b64s)} image(s) are the character ANCHOR reference(s). The remaining "
        f"images are candidate keyframes for this story beat.\n"
        f"BEAT: {beat.action} — setting: {beat.setting}.\n"
        f"Pick the best candidate (best_index, 0-based into candidates only) and score THAT one 1-5 on:\n"
        f"- prompt_adherence: matches the described scene\n"
        f"- style_consistency: matches the anchor art style + a flat bold comic look\n"
        f"- identity_vs_anchor: characters look EXACTLY like their anchor (face, colors, proportions)\n"
        f"- composition: clear, well-staged framing\n"
        f"- narrative_fit: reads as THIS story moment (right action + emotion)\n"
        f"Give a fix_prompt ONLY if the best candidate still needs work — a SHORT, specific edit "
        f"instruction (e.g. 'make the mane fuller to match the anchor; brighten the lighting'), else empty."
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


def score_frame(frame_b64: str, anchor_b64s: List[str], beat: Beat) -> Verdict:
    """Score a SINGLE keyframe on all reward axes (used inside the loop).

    best_index is forced to 0 (one frame). fix_prompt is the targeted edit to
    apply next if it hasn't cleared the threshold.
    """
    client = get_client()
    parts = [{"type": "text", "text": (
        f"The first {len(anchor_b64s)} image(s) are the character ANCHOR reference(s). "
        f"The final image is a candidate keyframe for this story beat.\n"
        f"BEAT: {beat.action} — setting: {beat.setting}.\n"
        f"Score the candidate 1-5 on: prompt_adherence, style_consistency, "
        f"identity_vs_anchor (looks exactly like the anchor), composition, narrative_fit "
        f"(reads as this exact story moment). Set best_index=0.\n"
        f"If ANY axis is below {THRESHOLD}, give a fix_prompt: ONE short, specific edit "
        f"instruction targeting the weakest axis (e.g. 'make the mane match the anchor', "
        f"'recenter the mouse', 'brighten to daylight'). If all axes are >= {THRESHOLD}, "
        f"leave fix_prompt empty."
    )}]
    for a in anchor_b64s:
        parts.append({"type": "image", "data": a, "mime_type": "image/png"})
    parts.append({"type": "image", "data": frame_b64, "mime_type": "image/png"})
    it = client.interactions.create(
        model=MODEL_TEXT,
        input=parts,
        response_format={"type": "text", "mime_type": "application/json",
                         "schema": Verdict.model_json_schema()},
    )
    v = Verdict.model_validate_json(it.output_text)
    v.best_index = 0
    return v


def _below_threshold(v: Verdict) -> bool:
    return _reward(v) < THRESHOLD


def _edit_frame(frame_b64: str, beat: Beat, anchor_b64s: List[str], fix: str) -> str:
    """Apply ONE targeted edit to the SAME frame (iterative refinement, not regen).

    We re-render the beat with the fix instruction, passing the current frame AND
    the anchors as references so the edit nudges the existing composition toward
    the fix rather than sampling a brand-new image from scratch.
    """
    prompt = (
        f"{beat.image_prompt}. TARGETED FIX: {fix}. {style_clause()} "
        f"Keep the overall composition of the provided keyframe; change only what the "
        f"fix requires. Keep every character identical to the anchor reference(s)."
    )
    # refs: current frame first (the thing being edited), then the anchors.
    return gen_image(prompt, refs=[frame_b64] + anchor_b64s)


def reward_loop(beat: Beat, board: Storyboard, candidates_b64: List[str],
                anchor_b64s: List[str], max_iters: int = MAX_ITERS
                ) -> Tuple[str, List[dict]]:
    """Verifier-guided keyframe search. Returns (best_frame_b64, trajectory).

    trajectory[i] = {iter, scores{axis:1-5}, reward, total, fix, earned} — the
    per-iteration record that powers the live "watch it earn the frame" demo.
    """
    trajectory: List[dict] = []

    # --- seed: pick the best of the fan-out candidates in one multi-candidate pass
    if len(candidates_b64) > 1:
        seed_v = critique(candidates_b64, anchor_b64s, beat)
        seed_idx = max(0, min(seed_v.best_index, len(candidates_b64) - 1))
    else:
        seed_idx = 0
        seed_v = score_frame(candidates_b64[0], anchor_b64s, beat)
    frame = candidates_b64[seed_idx]

    best_frame, best_total = frame, _total(seed_v)
    trajectory.append({
        "iter": 0, "kind": "seed", "scores": _scores_dict(seed_v),
        "reward": _reward(seed_v), "total": _total(seed_v),
        "fix": seed_v.fix_prompt, "earned": _reward(seed_v) >= THRESHOLD,
    })
    print(f"  beat {beat.beat_id} iter0(seed): reward={_reward(seed_v)} "
          f"axes={_scores_dict(seed_v)}" + (" EARNED" if _reward(seed_v) >= THRESHOLD else ""))

    v = seed_v
    for i in range(1, max_iters + 1):
        if _reward(v) >= THRESHOLD:
            break                                   # earned — stop early
        if not v.fix_prompt:
            break                                   # critic has no actionable fix
        try:
            frame = _edit_frame(frame, beat, anchor_b64s, v.fix_prompt)
        except Exception as e:
            print(f"  beat {beat.beat_id} iter{i}: edit failed ({e}); stopping")
            break
        v = score_frame(frame, anchor_b64s, beat)
        if _total(v) > best_total:                  # keep best-seen (reward may plateau)
            best_frame, best_total = frame, _total(v)
        earned = _reward(v) >= THRESHOLD
        trajectory.append({
            "iter": i, "kind": "edit", "scores": _scores_dict(v),
            "reward": _reward(v), "total": _total(v),
            "fix": v.fix_prompt, "earned": earned,
        })
        print(f"  beat {beat.beat_id} iter{i}: reward={_reward(v)} axes={_scores_dict(v)}"
              + (" EARNED" if earned else f" -> fix: {v.fix_prompt[:40]}"))

    # if the final frame is the best-seen, prefer it; else return best-seen
    if _total(v) >= best_total:
        best_frame = frame
    return best_frame, trajectory


def select_best(beat: Beat, board: Storyboard, candidates_b64: List[str],
                anchor_b64s: List[str]) -> str:
    """Back-compat wrapper: run the reward loop, return just the winning frame."""
    frame, _ = reward_loop(beat, board, candidates_b64, anchor_b64s)
    return frame


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
