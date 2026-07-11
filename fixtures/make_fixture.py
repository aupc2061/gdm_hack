"""Generate a stub selected.json + placeholder PNGs so video/ runs WITHOUT the
API key or story/'s real output.

Creates 3 beats of solid-color PNGs (keyframe + 2 anchors each) and writes
fixtures/selected.json in the exact seam format. video/run_video.py can then be
built and unit-tested against this offline. Only the live API calls inside
synth/narrate will fail without a key — everything else (io, stitch, reconcile
logic) is exercisable.

    python -m fixtures.make_fixture
"""

from __future__ import annotations

import os

from PIL import Image
from common.io import save_selected
from common.schema import SelectedFrame

HERE = os.path.dirname(os.path.abspath(__file__))

BEATS = [
    dict(beat_id=0, color=(196, 120, 60),
         motion_text="The lion sleeps in the sun. Wide establishing shot. [0-5s] slow push-in as the mouse scurries near.",
         duration_s=5.0,
         narration="Once, a mighty lion lay sleeping in the warm afternoon sun."),
    dict(beat_id=1, color=(90, 140, 90),
         motion_text="The lion catches the mouse under its paw; the mouse pleads. Medium shot. [0-4s] the lion's paw lifts.",
         duration_s=4.0,
         narration="A tiny mouse ran across his paw, and the lion awoke with a roar."),
    dict(beat_id=2, color=(120, 90, 160),
         motion_text="The mouse gnaws ropes of a hunter's net, freeing the lion. Close then wide. [0-6s] ropes snap.",
         duration_s=6.0,
         narration="Later, the little mouse gnawed the hunter's ropes and set the great lion free."),
]


def _swatch(path: str, color, label: str):
    img = Image.new("RGB", (1280, 720), color)
    img.save(path)


def main():
    frames = []
    for b in BEATS:
        kf = os.path.join(HERE, f"_kf{b['beat_id']}.png")
        a0 = os.path.join(HERE, f"_lion{b['beat_id']}.png")
        a1 = os.path.join(HERE, f"_mouse{b['beat_id']}.png")
        _swatch(kf, b["color"], "keyframe")
        _swatch(a0, (210, 150, 70), "lion")
        _swatch(a1, (150, 150, 150), "mouse")
        from common.io import png_to_b64
        frames.append(SelectedFrame(
            beat_id=b["beat_id"],
            selected_keyframe_b64=png_to_b64(kf),
            anchor_b64s=[png_to_b64(a0), png_to_b64(a1)],
            anchor_names=["lion", "mouse"],
            motion_text=b["motion_text"],
            duration_s=b["duration_s"],
            narration=b["narration"],
        ))
        for p in (kf, a0, a1):
            os.remove(p)
    path = save_selected(frames, HERE)
    print(f"wrote {path} + sidecar PNGs ({len(frames)} beats)")


if __name__ == "__main__":
    main()
