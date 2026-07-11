"""End-to-end story pipeline CLI: story text -> selected.json (+ PNGs).

Owner: Person 1. This is the whole story/ half. Its ONLY output that video/
consumes is the selected.json written by common.io.save_selected.

    python -m story.run_story --story "The Lion and the Mouse" --out out/run1
"""

from __future__ import annotations

import argparse

from common.io import save_selected
from common.schema import SelectedFrame
from story.director import direct_story
from story.anchors import generate_anchors
from story.keyframes import fan_out
from story.critic import select_best, harmonize

DEFAULT_STORY = "The Lion and the Mouse (Panchatantra): a mighty lion spares a tiny mouse; later the mouse gnaws the ropes of a hunter's net and frees the lion."


def _relevant_anchor_items(beat, anchors):
    txt = f"{beat.subject} {beat.action}".lower()
    items = [(n, b) for n, b in anchors.items() if n.lower() in txt]
    return items or list(anchors.items())


def run(story: str, out_dir: str, n_beats: int | None = None):
    print("[1/4] Director...")
    board = direct_story(story, n_beats=n_beats)
    print(f"  Director chose {len(board.beats)} beats; "
          f"characters: {[c.name for c in board.characters]}")

    print("[2/4] Anchors...")
    anchors = generate_anchors(board)

    print("[3/4] Keyframe fan-out...")
    candidates = fan_out(board, anchors)

    print("[4/5] Critic + per-beat selection...")
    frames = []
    picked_beats = []          # Beat objects, parallel to frames
    picked_anchors = []        # anchor b64 lists, parallel to frames
    for beat in board.beats:
        items = _relevant_anchor_items(beat, anchors)
        names = [n for n, _ in items]
        anchor_b64s = [b for _, b in items]
        cands = candidates[beat.beat_id]
        if not cands:
            print(f"  beat {beat.beat_id}: 0 candidates survived -> skipping. "
                  f"Re-run or loosen the prompt; video/ needs all beats.")
            continue
        best = select_best(beat, board, cands, anchor_b64s)
        frames.append(SelectedFrame(
            beat_id=beat.beat_id,
            selected_keyframe_b64=best,
            anchor_b64s=anchor_b64s,
            anchor_names=names,
            motion_text=f"{beat.action}. {beat.camera}. {beat.motion}",
            duration_s=beat.duration_s,
            narration=beat.narration,
        ))
        picked_beats.append(beat)
        picked_anchors.append(anchor_b64s)

    print("[5/5] Global consistency pass (judge all winners together)...")
    if len(frames) >= 2:
        harmonized = harmonize(picked_beats, [f.selected_keyframe_b64 for f in frames],
                               picked_anchors, max_fixes=2)
        for f, h in zip(frames, harmonized):
            f.selected_keyframe_b64 = h
    else:
        print("  <2 beats, nothing to harmonize")

    path = save_selected(frames, out_dir)
    print(f"\nDONE -> {path}  ({len(frames)} beats). Hand this dir to video/.")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", default=DEFAULT_STORY)
    ap.add_argument("--out", default="out/run1")
    ap.add_argument("--beats", type=int, default=None,
                    help="Force an exact beat count. Omit to let the Director choose from the story.")
    args = ap.parse_args()
    run(args.story, args.out, args.beats)
