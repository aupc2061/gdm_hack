"""End-to-end video pipeline CLI: selected.json -> final short.

Owner: Person 2. This is the whole video/ half. It reads ONLY the seam object
(SelectedFrame via common.io.load_selected) — never imports story/ code.

Build against fixtures/selected.json from minute one; swap to story/'s real
output at integration.

    python -m video.run_video --selected fixtures/selected.json --out out/run1
"""

from __future__ import annotations

import argparse
import os

from common.io import load_selected
from video.synth import synth_all
from video.narrate import narrate
from video.stitch import build_final


def run(selected_json: str, out_dir: str = "out/video"):
    os.makedirs(out_dir, exist_ok=True)
    frames = load_selected(selected_json)
    print(f"[1/3] Synth {len(frames)} beats (Omni, store=True)...")
    beat_clips = synth_all(frames, out_dir)

    print("[2/3] Narrate...")
    by_id = {fr.beat_id: fr for fr in frames}
    for bc in beat_clips:
        wav = os.path.join(out_dir, f"beat{bc.beat_id}.wav")
        narrate(by_id[bc.beat_id].narration, wav)
        bc.wav_path = wav

    print("[3/3] Reconcile + stitch...")
    final = build_final(beat_clips, os.path.join(out_dir, "chitrakatha.mp4"))
    print(f"\nDONE -> {final}")
    print("Omni interaction ids (for live re-direction):")
    for bc in beat_clips:
        print(f"  beat {bc.beat_id}: {bc.omni_interaction_id}")
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selected", default="fixtures/selected.json")
    ap.add_argument("--out", default="out/video")
    args = ap.parse_args()
    run(args.selected, args.out)
