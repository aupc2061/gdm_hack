"""Director agent: story text -> structured Storyboard.

Owner: Person 1 (story pipeline).

⚠️ VERIFY AT T+0: the structured-output shape on the Interactions API
(`response_format` with a JSON schema) is web-doc-derived, NOT cookbook-proven.
The cookbook used the OLD generate_content(config={'response_mime_type':...,
'response_schema':...}) form. Test a trivial 1-beat call first; if response_format
errors, use the fallback in `direct_story_fallback` below.
"""

from __future__ import annotations

from common.client import get_client, MODEL_TEXT
from common.schema import Storyboard

STYLE_LOCKED = "Amar Chitra Katha Indian comic-book illustration style, bold ink outlines, flat saturated colors"


def _prompt(story: str, n_beats: int, style: str, language: str) -> str:
    return (
        f"You are an animation director. Turn this folk tale into a {n_beats}-beat animated "
        f"storyboard. Story: {story}\n"
        f"Global visual style (apply to ALL beats): {style}.\n"
        f"Narration language: {language}.\n"
        f"Keep every character visually identical across beats. For each beat provide subject, "
        f"action, setting, camera, an explicit `motion` line for animation, a `duration_s` pacing "
        f"hint (2-6s by narrative weight), a one-sentence `narration` line written to fit that "
        f"duration (~2.5 words/sec), and a full `image_prompt` for the keyframe. "
        f"Also list every character/prop that needs a reference anchor with a `sheet_prompt`."
    )


def direct_story(story: str, n_beats: int = 3, style: str = STYLE_LOCKED,
                 language: str = "English") -> Storyboard:
    """PRIMARY path — structured output via response_format. VERIFY AT T+0."""
    client = get_client()
    it = client.interactions.create(
        model=MODEL_TEXT,
        input=_prompt(story, n_beats, style, language),
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": Storyboard.model_json_schema(),
        },
    )
    return Storyboard.model_validate_json(it.output_text)


def direct_story_fallback(story: str, n_beats: int = 3, style: str = STYLE_LOCKED,
                          language: str = "English") -> Storyboard:
    """FALLBACK — old generate_content config form (cookbook-proven).

    Use only if the primary response_format call fails at T+0.
    """
    client = get_client()
    resp = client.models.generate_content(
        model=MODEL_TEXT,
        contents=_prompt(story, n_beats, style, language),
        config={
            "response_mime_type": "application/json",
            "response_schema": Storyboard,
        },
    )
    return Storyboard.model_validate_json(resp.text)


if __name__ == "__main__":
    sb = direct_story("The Lion and the Mouse (Panchatantra)")
    print(sb.model_dump_json(indent=2))
