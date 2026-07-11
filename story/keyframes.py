"""Keyframe fan-out: per beat, 2 candidates conditioned on the relevant anchors.

Owner: Person 1. Parallel across beats (ThreadPoolExecutor) — this is the
multi-agent fan-out. No cross-beat continuity check by design.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from common.schema import Storyboard, Beat
from story.anchors import gen_image, ImageBlocked
from story.style import style_clause

N_CANDIDATES = 2


def _relevant_anchors(beat: Beat, anchors: Dict[str, str]) -> List[str]:
    """Pick anchors whose name is mentioned in the beat. Falls back to all anchors."""
    txt = f"{beat.subject} {beat.action}".lower()
    hits = [b64 for name, b64 in anchors.items() if name.lower() in txt]
    return hits or list(anchors.values())


def gen_candidates(beat: Beat, board: Storyboard, anchors: Dict[str, str],
                   n: int = N_CANDIDATES) -> List[str]:
    """Generate n candidate keyframes for one beat, conditioned on relevant anchors.

    A candidate blocked by the safety filter is skipped, not fatal — the Critic
    picks best-of-whatever-exists. Returns whatever succeeded (may be < n).
    """
    refs = _relevant_anchors(beat, anchors)
    prompt = (
        f"{beat.image_prompt}. {style_clause()} "
        f"Use the reference image(s) ONLY for character identity — keep every character "
        f"looking exactly like its reference (same face, colors, proportions)."
    )
    out: List[str] = []
    for _ in range(n):
        try:
            out.append(gen_image(prompt, refs=refs))
        except ImageBlocked as e:
            print(f"  beat {beat.beat_id}: candidate blocked, skipping ({e})")
    return out


def fan_out(board: Storyboard, anchors: Dict[str, str]) -> Dict[int, List[str]]:
    """Parallel across beats. Returns {beat_id: [candidate_b64, ...]}.

    A beat that yields zero candidates (all blocked) is still returned as an
    empty list so the caller can decide; it does not crash the other beats.
    """
    results: Dict[int, List[str]] = {}
    with ThreadPoolExecutor(max_workers=min(len(board.beats), 4)) as ex:
        futs = {ex.submit(gen_candidates, b, board, anchors): b.beat_id for b in board.beats}
        for fut, beat_id in list(futs.items()):
            try:
                results[beat_id] = fut.result()
            except Exception as e:
                print(f"  beat {beat_id}: FAILED ({type(e).__name__}: {str(e)[:80]}) -> 0 candidates")
                results[beat_id] = []
            print(f"  beat {beat_id}: {len(results[beat_id])} candidates")
    return results


if __name__ == "__main__":
    from story.director import direct_story
    from story.anchors import generate_anchors
    board = direct_story("The Lion and the Mouse (Panchatantra)")
    anchors = generate_anchors(board)
    cands = fan_out(board, anchors)
    print({k: len(v) for k, v in cands.items()})
