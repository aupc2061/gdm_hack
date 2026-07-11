"""Integration entry point: story pipeline -> video pipeline, end to end.

Built LAST, together, at the dry run. Until then each half runs via its own
CLI (story.run_story / video.run_video) against fixtures.

    python orchestrate.py --story "The Lion and the Mouse" --out out/full
"""

from __future__ import annotations

import argparse

from story.run_story import run as run_story, DEFAULT_STORY
from video.run_video import run as run_video


def main(story: str, out_dir: str):
    selected_json = run_story(story, out_dir)   # -> out_dir/selected.json (+PNGs)
    final = run_video(selected_json, out_dir)   # -> out_dir/chitrakatha.mp4
    print(f"\n=== FULL PIPELINE DONE -> {final} ===")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", default=DEFAULT_STORY)
    ap.add_argument("--out", default="out/full")
    args = ap.parse_args()
    main(args.story, args.out)
