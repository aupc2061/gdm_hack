# story/ — Person 1's half (Director → Anchor → Keyframe → Critic)

**Read the root `../CLAUDE.md` first** — it has the ownership rules, the frozen
seam, and the verified-vs-unverified API notes.

You own THIS folder. Do NOT edit `video/`. Your only deliverable to the other
half is `out/<run>/selected.json` (a `list[SelectedFrame]`), produced by
`run_story.py`. The seam is `common/schema.py` — do not change it alone.

Verify at T+0: the Director `response_format` structured-output call. If it
errors, use `direct_story_fallback` (proven `generate_content` form).
