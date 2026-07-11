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

# The Director chooses the beat count within this range. Bounded (not unlimited)
# because each beat = one slow Omni video call downstream (~60-90s); an unbounded
# count would make synthesis time and the final video length unpredictable.
MIN_BEATS = 3
MAX_BEATS = 6


def _beats_instruction(n_beats: int | None) -> str:
    if n_beats is not None:
        return f"Turn this folk tale into a {n_beats}-beat animated storyboard."
    return (
        f"Break this folk tale into a sequence of animated storyboard beats. "
        f"YOU decide how many beats the story needs — between {MIN_BEATS} and {MAX_BEATS} — "
        f"based on its narrative complexity. A simple tale with a single turning point needs "
        f"about {MIN_BEATS}; a richer tale with several distinct events or locations needs more. "
        f"Use only as many beats as the story genuinely requires; do not pad a simple story or "
        f"over-compress a complex one."
    )


def _prompt(story: str, n_beats: int | None, style: str, language: str) -> str:
    return (
        f"You are an animation director. {_beats_instruction(n_beats)} Story: {story}\n"
        f"Global visual style (apply to ALL beats): {style}.\n"
        f"Narration language: {language}.\n"
        f"Keep every character visually identical across beats. Number beats sequentially "
        f"starting at 0. For each beat provide subject, action, setting, camera, an explicit "
        f"`motion` line for animation, a `duration_s` pacing hint (2-6s by narrative weight), a "
        f"one-sentence `narration` line written to fit that duration (~2.5 words/sec), and a full "
        f"`image_prompt` for the keyframe. Also list every character/prop that needs a reference "
        f"anchor with a `sheet_prompt`."
    )


def _normalize_beats(board: Storyboard) -> Storyboard:
    """Renumber beat_id sequentially 0..n-1 so downstream keying is reliable
    regardless of how the model numbered them."""
    for i, b in enumerate(board.beats):
        b.beat_id = i
    return board


def direct_story(story: str, n_beats: int | None = None, style: str = STYLE_LOCKED,
                 language: str = "English") -> Storyboard:
    """PRIMARY path — structured output via response_format. VERIFY AT T+0.

    n_beats=None (default) lets the Director choose the beat count from the story
    (bounded MIN_BEATS..MAX_BEATS). Pass an int to force an exact count.
    """
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
    return _normalize_beats(Storyboard.model_validate_json(it.output_text))


def direct_story_fallback(story: str, n_beats: int | None = None, style: str = STYLE_LOCKED,
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
    return _normalize_beats(Storyboard.model_validate_json(resp.text))


if __name__ == "__main__":
    sb = direct_story("The Lion and the Mouse (Panchatantra)")
    print(sb.model_dump_json(indent=2))
