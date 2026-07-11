"""Keyframe fan-out: per beat, 2 candidates conditioned on the relevant anchors.

Owner: Person 1. Parallel across beats (ThreadPoolExecutor) — this is the
multi-agent fan-out. No cross-beat continuity check by design.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from common.schema import Storyboard, Beat
from story.anchors import gen_image

N_CANDIDATES = 2


def _relevant_anchors(beat: Beat, anchors: Dict[str, str]) -> List[str]:
    """Pick anchors whose name is mentioned in the beat. Falls back to all anchors."""
    txt = f"{beat.subject} {beat.action}".lower()
    hits = [b64 for name, b64 in anchors.items() if name.lower() in txt]
    return hits or list(anchors.values())


def gen_candidates(beat: Beat, board: Storyboard, anchors: Dict[str, str],
                   n: int = N_CANDIDATES) -> List[str]:
    """Generate n candidate keyframes for one beat, conditioned on relevant anchors."""
    refs = _relevant_anchors(beat, anchors)
    prompt = (
        f"{beat.image_prompt}. Style: {board.global_style}. "
        f"Use the reference image(s) ONLY for character/style identity — keep characters identical."
    )
    return [gen_image(prompt, refs=refs) for _ in range(n)]


def fan_out(board: Storyboard, anchors: Dict[str, str]) -> Dict[int, List[str]]:
    """Parallel across beats. Returns {beat_id: [candidate_b64, ...]}."""
    results: Dict[int, List[str]] = {}
    with ThreadPoolExecutor(max_workers=len(board.beats)) as ex:
        futs = {ex.submit(gen_candidates, b, board, anchors): b.beat_id for b in board.beats}
        for fut, beat_id in list(futs.items()):
            results[beat_id] = fut.result()
            print(f"  beat {beat_id}: {len(results[beat_id])} candidates")
    return results


if __name__ == "__main__":
    from story.director import direct_story
    from story.anchors import generate_anchors
    board = direct_story("The Lion and the Mouse (Panchatantra)")
    anchors = generate_anchors(board)
    cands = fan_out(board, anchors)
    print({k: len(v) for k, v in cands.items()})
