"""Conversational re-direction — the Idea-4 money shot.

Owner: Person 2. Stateful edit of a previously generated (store=True) Omni clip
via previous_interaction_id. Re-synthesizes ONLY that segment.

VERIFIED 2026-07-10 (out/probe): works. The prior call must have used store=True
(synth.py does). Free-tier interactions expire in ~1 day, so re-direct in the
same session you generated.

DEMO PLAN: scripted live on a SHORT single-beat clip. Keep the edit prompt
surgical, ending with "Keep everything else the same." Have a screen recording
of a known-good run as fallback.
"""

from __future__ import annotations

import argparse
import base64
import json
import os

from common.client import get_client, MODEL_VIDEO


def redirect(prev_interaction_id: str, edit_prompt: str,
             out_path: str = "out/redirect.mp4") -> str:
    """Apply a conversational edit to a prior Omni clip. Returns out_path."""
    client = get_client()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    it = client.interactions.create(
        model=MODEL_VIDEO,
        previous_interaction_id=prev_interaction_id,
        input=edit_prompt,
    )
    data = it.output_video.data
    if isinstance(data, str):
        data = base64.b64decode(data)
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"redirect -> {out_path} (new interaction {it.id})")
    return out_path


def redirect_beat(interactions_json: str, beat_id: int, edit_prompt: str,
                  out_path: str | None = None) -> str:
    """Look up a beat's stored Omni interaction id and re-direct it.

    interactions_json is the file run_video.py writes ({"0": "<id>", ...}).
    """
    with open(interactions_json) as f:
        ids = json.load(f)
    iid = ids.get(str(beat_id))
    if not iid:
        raise KeyError(f"no interaction id for beat {beat_id} in {interactions_json}")
    if out_path is None:
        out_path = os.path.join(os.path.dirname(interactions_json), f"beat{beat_id}_redirect.mp4")
    return redirect(iid, edit_prompt, out_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Conversationally re-direct one beat.")
    ap.add_argument("--interactions", help="path to interactions.json from run_video")
    ap.add_argument("--beat", type=int, help="beat_id to edit (with --interactions)")
    ap.add_argument("--id", help="raw interaction id (alternative to --interactions/--beat)")
    ap.add_argument("--prompt", default="Make it night time. Keep everything else the same.")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.interactions and args.beat is not None:
        redirect_beat(args.interactions, args.beat, args.prompt, args.out)
    elif args.id:
        redirect(args.id, args.prompt, args.out or "out/redirect.mp4")
    else:
        ap.error("provide either --interactions + --beat, or --id")
