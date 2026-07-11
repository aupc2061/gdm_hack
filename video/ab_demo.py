"""A/B demo device: naive text->video vs. ChitraKatha, side by side.

Owner: Person 2. Sells the novelty WITHOUT explaining internals — the audience
sees the difference. The 'naive' side is the black box the Idea-4 brief
describes: one text_to_video call, no storyboard, no anchors, no consistency.
The 'ours' side is the storyboard-conditioned, identity-locked short.

    # 1. generate the naive baseline for a story (one Omni text->video call)
    python -m video.ab_demo naive --story "The Lion and the Mouse" --out out/ab

    # 2. compose side-by-side against an existing ChitraKatha short
    python -m video.ab_demo compose --naive out/ab/naive.mp4 \
        --ours out/stage3/chitrakatha.mp4 --out out/ab/ab_compare.mp4
"""

from __future__ import annotations

import argparse
import base64
import os

from common.client import get_client, MODEL_VIDEO

NAIVE_STORY = ("The Lion and the Mouse: a mighty lion spares a tiny mouse, and later "
               "the mouse frees the lion from a hunter's net.")


def gen_naive(story: str, out_dir: str) -> str:
    """The black-box baseline: a single text->video call for the WHOLE story.
    No storyboard, no keyframes, no anchor — this is what 'type a prompt, get a
    clip' produces, and it drifts/compresses the narrative into one incoherent shot.
    """
    client = get_client()
    os.makedirs(out_dir, exist_ok=True)
    it = client.interactions.create(
        model=MODEL_VIDEO,
        input=f"Animate this whole story as a video: {story}",
        response_format={"type": "video", "aspect_ratio": "16:9"},
    )
    data = it.output_video.data
    out = os.path.join(out_dir, "naive.mp4")
    with open(out, "wb") as f:
        f.write(base64.b64decode(data) if isinstance(data, str) else data)
    print(f"naive baseline -> {out}")
    return out


def _labeled(clip, text, font_size=40):
    """Overlay a caption bar at the top of a clip (moviepy 2.x). Falls back to
    the bare clip if TextClip/font is unavailable in the environment."""
    from moviepy import TextClip, CompositeVideoClip
    try:
        txt = (TextClip(text=text, font_size=font_size, color="white",
                        bg_color="black", size=(clip.w, 56))
               .with_duration(clip.duration).with_position(("center", "top")))
        return CompositeVideoClip([clip, txt])
    except Exception as e:
        print(f"  (label skipped: {type(e).__name__} — showing unlabeled)")
        return clip


def compose(naive_path: str, ours_path: str, out_path: str,
            label: bool = True) -> str:
    """Side-by-side: naive (left) vs ChitraKatha (right), matched height, looped
    to the longer duration so both play through."""
    from moviepy import VideoFileClip, clips_array

    naive = VideoFileClip(naive_path).resized(height=480)
    ours = VideoFileClip(ours_path).resized(height=480)

    if label:
        naive = _labeled(naive, "Naive text->video")
        ours = _labeled(ours, "ChitraKatha")

    grid = clips_array([[naive, ours]])
    grid.write_videofile(out_path, fps=24)
    naive.close(); ours.close(); grid.close()
    print(f"A/B comparison -> {out_path}")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="A/B: naive text->video vs ChitraKatha.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_naive = sub.add_parser("naive", help="generate the naive baseline clip")
    p_naive.add_argument("--story", default=NAIVE_STORY)
    p_naive.add_argument("--out", default="out/ab")

    p_comp = sub.add_parser("compose", help="compose naive + ours side by side")
    p_comp.add_argument("--naive", required=True)
    p_comp.add_argument("--ours", required=True)
    p_comp.add_argument("--out", default="out/ab/ab_compare.mp4")
    p_comp.add_argument("--no-label", action="store_true")

    args = ap.parse_args()
    if args.cmd == "naive":
        gen_naive(args.story, args.out)
    elif args.cmd == "compose":
        compose(args.naive, args.ours, args.out, label=not args.no_label)
