"""Canonical visual contract — the ONE source of truth for how every image looks.

Why this file exists: coherence across beats was drifting because (a) the Director
paraphrased the style differently each run, (b) each keyframe rolled independently
with no shared enforcement, and (c) anchors carried baked-in label text that bled
into scenes. Centralizing the rules here — used verbatim by anchors, keyframes, and
the critic — is the "global candidate for style": one look, applied everywhere.
"""

from __future__ import annotations

# The locked look. Kept concrete and unambiguous so the model can't reinterpret it
# per-call. Do NOT let the Director's free-text style override this.
STYLE_CONTRACT = (
    "Amar Chitra Katha Indian comic-book illustration: uniform bold medium-weight "
    "black ink outlines, flat evenly-filled saturated colors, clean cel shading, "
    "bright even golden daylight in EVERY panel regardless of the scene's mood, "
    "consistent warm sunlit palette across every panel, never dark or desaturated "
    "or twilight"
)

# Appended to EVERY image prompt. Kills the caption boxes, panel borders, and
# printed frames we saw drifting in — and, critically, stops Omni from later
# animating baked-in text as an artifact.
NO_TEXT = (
    "No text, no letters, no words, no captions, no speech bubbles, no title, "
    "no signature, no watermark, no panel border, no frame, no vignette. "
    "Full-bleed illustration only"
)


def style_clause() -> str:
    """The style + anti-text block to append to any scene/keyframe prompt."""
    return f"Style: {STYLE_CONTRACT}. {NO_TEXT}."


def anchor_prompt(sheet_prompt: str) -> str:
    """Prompt for a clean single-portrait character anchor.

    Single canonical pose on plain background — a stronger identity lock than a
    multi-pose 'model sheet', and with no labels to leak into keyframes.
    """
    return (
        f"{sheet_prompt}. {style_clause()} "
        f"One single character, front-facing full-body portrait, centered, "
        f"plain flat solid neutral background, no other characters, no props, "
        f"no scenery. Character reference — clean and label-free."
    )
