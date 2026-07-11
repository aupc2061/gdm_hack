"""ChitraKatha — full end-to-end pipeline in ONE command.

Story text -> Director storyboard -> per-character anchors -> keyframe fan-out ->
verifier-guided reward loop (best keyframe per beat) -> global harmonize ->
Omni video synthesis (guardrail-resilient) -> stitch -> consistency enforcement
(anchor-derived typed primitives, auto re-direct) -> final short.

    python orchestrate.py                         # guardrail-safe default (crow)
    python orchestrate.py --story "..." --out out/mydemo
    python orchestrate.py --no-enforce            # skip the consistency net (faster)

Default story is the Thirsty Crow — verified to clear BOTH content guardrails
(no violence) and the IP guardrail (a crow doesn't resemble copyrighted
characters, unlike a Lion-King-ish lion). Swap --story at your own risk; test
new stories for guardrail trips first.
"""

from __future__ import annotations

import argparse

from story.run_story import run as run_story
from video.run_video import run as run_video

# Guardrail-safe demo story (verified end-to-end 2026-07-11): no violence, no IP
# resemblance. Culturally Indian, teaches cleverness — strong "Impact in India".
CROW_STORY = (
    "The Thirsty Crow (a classic Indian Panchatantra tale): On a hot sunny day, a "
    "clever black crow flies across a dry Indian village looking for water. It finds "
    "an earthen clay pot with only a little water at the very bottom, too low to reach. "
    "The clever crow gathers small pebbles and drops them one by one into the pot, and "
    "the water slowly rises to the top. The happy crow drinks the cool water. A cheerful "
    "story about cleverness, patience, and problem-solving."
)


def main(story: str, out_dir: str, enforce: bool = True):
    print("=" * 60)
    print("CHITRAKATHA — full pipeline")
    print("=" * 60)

    print("\n### STAGE A — Story pipeline (Director -> reward loop -> harmonize)")
    selected_json = run_story(story, out_dir)     # -> out_dir/selected.json (+PNGs)

    print("\n### STAGE B — Video (synth -> stitch" +
          (" -> consistency enforce)" if enforce else ")"))
    final = run_video(selected_json, out_dir, enforce=enforce)

    print(f"\n{'=' * 60}\n=== FULL PIPELINE DONE -> {final} ===\n{'=' * 60}")
    if enforce:
        print(f"(consistency report + interaction ids in {out_dir}/)")
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ChitraKatha full end-to-end pipeline.")
    ap.add_argument("--story", default=CROW_STORY, help="story text (default: guardrail-safe crow)")
    ap.add_argument("--out", default="out/full", help="output directory")
    ap.add_argument("--no-enforce", action="store_true",
                    help="skip the consistency enforcement net (faster, no auto re-direct)")
    args = ap.parse_args()
    main(args.story, args.out, enforce=not args.no_enforce)
