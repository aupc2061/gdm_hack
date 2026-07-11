# video/ — Person 2's half (Omni synth → TTS → stitch → re-direction)

**Read the root `../CLAUDE.md` first** — it has the ownership rules, the frozen
seam, and the verified-vs-unverified API notes.

You own THIS folder. Do NOT edit `story/`. You consume the seam object
(`common.io.load_selected` → `list[SelectedFrame]`); build against
`fixtures/selected.json` from minute one — no need to wait for story/.

Do FIRST at T+0: `python -m video.synth` smoke_test — prove the combined
`FIRST_FRAME`+`IMAGE_REF_N` call binds refs, measure Omni latency + actual clip
length. If refs don't bind, set `USE_COMBINED = False` (proven keyframe-only
fallback). Keep `store=True` on every Omni call (needed for redirect.py).
