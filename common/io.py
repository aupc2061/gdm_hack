"""Serialization helpers for the story <-> video seam.

selected.json holds a list of SelectedFrame. To keep the JSON readable and
small, base64 image blobs are written to sidecar PNGs and referenced by path;
load_selected() rehydrates them back into b64 strings so video/ code only ever
sees SelectedFrame objects with inline b64.
"""

from __future__ import annotations

import base64
import json
import os
from typing import List

from common.schema import SelectedFrame


def b64_to_png(b64: str, path: str) -> None:
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))


def png_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def save_selected(frames: List[SelectedFrame], out_dir: str) -> str:
    """Write selected.json + sidecar PNGs. Returns the json path.

    story/ calls this; video/ never does.
    """
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    for fr in frames:
        kf_path = os.path.join(out_dir, f"beat{fr.beat_id}_keyframe.png")
        b64_to_png(fr.selected_keyframe_b64, kf_path)
        anchor_paths = []
        for i, ab in enumerate(fr.anchor_b64s):
            ap = os.path.join(out_dir, f"beat{fr.beat_id}_anchor{i}.png")
            b64_to_png(ab, ap)
            anchor_paths.append(os.path.basename(ap))
        manifest.append({
            "beat_id": fr.beat_id,
            "keyframe_png": os.path.basename(kf_path),
            "anchor_pngs": anchor_paths,
            "anchor_names": fr.anchor_names,
            "motion_text": fr.motion_text,
            "duration_s": fr.duration_s,
            "narration": fr.narration,
        })
    json_path = os.path.join(out_dir, "selected.json")
    with open(json_path, "w") as f:
        json.dump(manifest, f, indent=2)
    return json_path


def load_selected(json_path: str) -> List[SelectedFrame]:
    """Read selected.json (+ sidecar PNGs) into SelectedFrame objects.

    video/ calls this. The base dir is inferred from json_path.
    """
    base = os.path.dirname(os.path.abspath(json_path))
    with open(json_path) as f:
        manifest = json.load(f)
    frames = []
    for m in manifest:
        frames.append(SelectedFrame(
            beat_id=m["beat_id"],
            selected_keyframe_b64=png_to_b64(os.path.join(base, m["keyframe_png"])),
            anchor_b64s=[png_to_b64(os.path.join(base, p)) for p in m["anchor_pngs"]],
            anchor_names=m.get("anchor_names", []),
            motion_text=m["motion_text"],
            duration_s=m["duration_s"],
            narration=m["narration"],
        ))
    return frames
