"""Conversational re-direction — the Idea-4 money shot.

Owner: Person 2. Stateful edit of a previously generated (store=True) Omni
clip via previous_interaction_id. Re-synthesizes ONLY that segment.

DEMO PLAN: scripted live on a SHORT single-beat clip. Keep the edit prompt
surgical ("Make it night time. Keep everything else the same."). Have a screen
recording of a known-good run as fallback.

REQUIRES: the target beat was synthesized with store=True (synth.py does this)
and within the retention window (free tier = 1 day!).
"""

from __future__ import annotations

import base64
import os

from common.client import get_client, MODEL_VIDEO


def redirect(prev_interaction_id: str, edit_prompt: str,
             out_path: str = "out/redirect.mp4") -> str:
    """Apply a conversational edit to a prior Omni clip. Returns out_path.

    edit_prompt should be short + surgical, ending with
    'Keep everything else the same.'
    """
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


if __name__ == "__main__":
    import sys
    # usage: python -m video.redirect <prev_interaction_id> "Make it night time. Keep everything else the same."
    redirect(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Make it night time. Keep everything else the same.")
