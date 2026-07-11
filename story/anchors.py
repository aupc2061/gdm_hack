"""Anchor generation: one reference image PER character/prop (the consistency key).

Owner: Person 1. Uses the cookbook-confirmed image shape
(response_modalities=["image"] + image_config), NOT response_format.
"""

from __future__ import annotations

from typing import Dict, List
from common.client import get_client, MODEL_IMAGE
from common.schema import Storyboard


def gen_image(prompt: str, refs: List[str] | None = None,
              model: str = MODEL_IMAGE, ar: str = "16:9") -> str:
    """Generate one image. Returns base64 PNG (str). refs = optional b64 reference images."""
    client = get_client()
    parts = [{"type": "text", "text": prompt}]
    for r in (refs or []):
        parts.append({"type": "image", "data": r, "mime_type": "image/png"})
    it = client.interactions.create(
        model=model,
        input=parts,
        response_modalities=["image"],
        generation_config={"image_config": {"aspect_ratio": ar}},
    )
    part = it.output_image
    data = part.data
    # .data may be base64 str or raw bytes depending on SDK build — normalize to b64 str
    if isinstance(data, bytes):
        import base64
        return base64.b64encode(data).decode()
    return data


def generate_anchors(board: Storyboard) -> Dict[str, str]:
    """One anchor per character/prop. Returns {name: b64_png}.

    Sequential is fine (2-3 chars); parallelize with ThreadPoolExecutor if slow.
    """
    anchors: Dict[str, str] = {}
    for ch in board.characters:
        prompt = f"{ch.sheet_prompt}. Style: {board.global_style}. Single character on plain background, full body, reference sheet."
        anchors[ch.name] = gen_image(prompt)
        print(f"  anchor generated: {ch.name}")
    return anchors


if __name__ == "__main__":
    from story.director import direct_story
    board = direct_story("The Lion and the Mouse (Panchatantra)")
    a = generate_anchors(board)
    print(f"{len(a)} anchors: {list(a)}")
