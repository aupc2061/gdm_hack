"""End-to-end video pipeline CLI: selected.json -> final short.

Owner: Person 2. This is the whole video/ half. It reads ONLY the seam object
(SelectedFrame via common.io.load_selected) — never imports story/ code.

DEFAULT: Omni native audio (no TTS). Pass --narrate to add TTS narration
(fallback if Omni audio is poor); --mix to layer TTS over Omni's audio.

Build against fixtures/selected.json from minute one; swap to story/'s real
output at integration.

    python -m video.run_video --selected fixtures/selected.json --out out/run1
    python -m video.run_video --selected fixtures/selected.json --narrate
"""

from __future__ import annotations

import argparse
import json
import os

from common.io import load_selected
from video.synth import synth_all
from video.narrate import narrate
from video.stitch import build_final


def run(selected_json: str, out_dir: str = "out/video",
        do_narrate: bool = False, mix: bool = False, think: bool = False,
        enforce: bool = False):
    os.makedirs(out_dir, exist_ok=True)
    frames = load_selected(selected_json)

    tag = " + thinking" if think else ""
    print(f"[1/3] Synth {len(frames)} beats (Omni image_to_video, store=True{tag})...")
    beat_clips = synth_all(frames, out_dir, think=think)

    if not beat_clips:
        raise RuntimeError("All beats were blocked/failed — nothing to stitch. "
                           "Check guardrail blocks above; soften the motion text or re-run.")
    if len(beat_clips) < len(frames):
        got = {bc.beat_id for bc in beat_clips}
        missing = [fr.beat_id for fr in frames if fr.beat_id not in got]
        print(f"  NOTE: {len(beat_clips)}/{len(frames)} beats rendered; missing {missing} (guardrail-blocked).")

    if do_narrate:
        print("[2/3] Narrate (TTS)...")
        by_id = {fr.beat_id: fr for fr in frames}
        for bc in beat_clips:
            wav = os.path.join(out_dir, f"beat{bc.beat_id}.wav")
            narrate(by_id[bc.beat_id].narration, wav)
            bc.wav_path = wav
    else:
        print("[2/3] Skipping TTS — using Omni native audio.")

    print("[3/3] Stitch...")
    final = build_final(beat_clips, os.path.join(out_dir, "chitrakatha.mp4"),
                        narrate=do_narrate, keep_native=mix)

    # Persist interaction ids — Stage-4 re-direction + demo need them
    # (free-tier interactions expire in ~1 day).
    ids = {str(bc.beat_id): bc.omni_interaction_id for bc in beat_clips}
    with open(os.path.join(out_dir, "interactions.json"), "w") as f:
        json.dump(ids, f, indent=2)

    print(f"\nDONE -> {final}")
    print(f"Omni interaction ids -> {os.path.join(out_dir, 'interactions.json')}")
    for bid, iid in ids.items():
        print(f"  beat {bid}: {iid}")

    if enforce:
        # Post-render consistency net: derive per-beat primitives from the story's
        # anchors, check each rendered beat, auto re-direct violators, re-stitch.
        print("\n[4/4] Consistency enforcement (anchor-derived primitives)...")
        from video.consistency import enforce_run
        report = enforce_run(out_dir, selected_json)
        with open(os.path.join(out_dir, "consistency_report.json"), "w") as f:
            json.dump(report, f, indent=2)
        print(f"Consistency report -> {os.path.join(out_dir, 'consistency_report.json')}")
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selected", default="fixtures/selected.json")
    ap.add_argument("--out", default="out/video")
    ap.add_argument("--narrate", action="store_true", help="add TTS narration (fallback path)")
    ap.add_argument("--mix", action="store_true", help="with --narrate, layer TTS over Omni audio")
    ap.add_argument("--think", action="store_true",
                    help="pre-bake with Omni reasoning captured per beat (slower ~1.8x)")
    ap.add_argument("--enforce", action="store_true",
                    help="post-render consistency net: check beats vs anchor-derived primitives, auto re-direct")
    args = ap.parse_args()
    run(args.selected, args.out, do_narrate=args.narrate, mix=args.mix, think=args.think,
        enforce=args.enforce)
