"""Anchor generation: one reference image PER character/prop (the consistency key).

Owner: Person 1. Uses the cookbook-confirmed image shape
(response_modalities=["image"] + image_config), NOT response_format.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Dict, List

from PIL import Image

from common.client import get_client, MODEL_IMAGE
from common.schema import Storyboard
from story.style import anchor_prompt


class ImageBlocked(Exception):
    """Raised when the image model refuses a prompt after all retries."""


def _to_png_b64(data) -> str:
    """Normalize model output (b64 str or raw bytes, any format) to base64 PNG.

    The image model returns JPEG despite our image/png labels; the seam
    (io.py PNG sidecars, Omni's mime_type=image/png refs) assumes real PNG.
    Re-encode so the bytes match the label everyone downstream trusts.
    """
    raw = base64.b64decode(data) if isinstance(data, str) else data
    img = Image.open(io.BytesIO(raw))
    if img.format == "PNG":
        return base64.b64encode(raw).decode()
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def gen_image(prompt: str, refs: List[str] | None = None,
              model: str = MODEL_IMAGE, ar: str = "16:9", retries: int = 2) -> str:
    """Generate one image. Returns base64 PNG (str). refs = optional b64 reference images.

    The image safety filter is intermittent — benign prompts (a trapped lion)
    get blocked on one call and pass on the next. Retry a few times before
    giving up so a single flaky block doesn't sink a live-demo run.
    """
    client = get_client()
    parts = [{"type": "text", "text": prompt}]
    for r in (refs or []):
        parts.append({"type": "image", "data": r, "mime_type": "image/png"})
    last_exc = None
    for attempt in range(retries + 1):
        try:
            it = client.interactions.create(
                model=model,
                input=parts,
                response_modalities=["image"],
                generation_config={"image_config": {"aspect_ratio": ar}},
            )
            return _to_png_b64(it.output_image.data)
        except Exception as e:
            last_exc = e
            if "prohibited content" not in str(e).lower() and "blocked" not in str(e).lower():
                raise  # a real error (auth, network) — don't mask it
            if attempt < retries:
                time.sleep(1.5)
    raise ImageBlocked(f"blocked after {retries + 1} attempts: {str(last_exc)[:120]}")


def generate_anchors(board: Storyboard) -> Dict[str, str]:
    """One anchor per character/prop. Returns {name: b64_png}.

    Sequential is fine (2-3 chars); parallelize with ThreadPoolExecutor if slow.
    """
    anchors: Dict[str, str] = {}
    for ch in board.characters:
        anchors[ch.name] = gen_image(anchor_prompt(ch.sheet_prompt))
        print(f"  anchor generated: {ch.name}")
    return anchors


if __name__ == "__main__":
    from story.director import direct_story
    board = direct_story("The Lion and the Mouse (Panchatantra)")
    a = generate_anchors(board)
    print(f"{len(a)} anchors: {list(a)}")
