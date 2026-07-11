# ChitraKatha (चित्रकथा)

Narrate a folk tale → a team of agents storyboards it, generates anchor-consistent
keyframes, animates a multi-shot narrated short, then lets you re-direct any shot
by conversation. GDM Bangalore Hackathon — **Idea 4** (Conversational Video &
Motion, NB2 Lite → Omni Flash).

Full spec: [`ps_final.md`](ps_final.md) · API cheat-sheet: [`api_ref.md`](api_ref.md)

## Architecture — two independently-runnable halves

```
common/            shared contract (imported by both, changed by neither alone)
  schema.py          Pydantic models for every seam object
  client.py          genai client + model IDs + `python -m common.client` check
  io.py              save/load the story->video seam (selected.json + PNGs)

story/   (Person 1)  Director -> Anchor -> Keyframe -> Critic
  run_story.py       CLI: story text -> out/<run>/selected.json (+PNGs)

video/   (Person 2)  Omni synth -> TTS -> stitch -> re-direction
  run_video.py       CLI: selected.json -> out/<run>/chitrakatha.mp4
  synth.py           ⚠️ has smoke_test() — run FIRST on hackathon day

fixtures/            stub selected.json so video/ runs without story/ or a key
orchestrate.py       integration only (built together at the dry run)
```

**The only thing that crosses folders is `list[SelectedFrame]`** (see
`common/schema.py`), serialized as `selected.json`. story/ produces it, video/
consumes it. Neither imports the other.

## Setup

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="..."          # from aistudio.google.com/api-keys
python -m common.client               # T+0: confirm all model IDs resolve
```

## Working in parallel (the whole point)

**Person 1 (story/):**
```bash
python -m story.run_story --story "The Lion and the Mouse" --out out/run1
# -> out/run1/selected.json  (this is your deliverable to video/)
```

**Person 2 (video/)** — start against the fixture, no story/ needed:
```bash
python -m fixtures.make_fixture                       # writes fixtures/selected.json
python -m video.synth                                 # T+0 SMOKE TEST (edit paths first)
python -m video.run_video --selected fixtures/selected.json --out out/vtest
```

**Full pipeline (one command):**
```bash
python orchestrate.py                 # guardrail-safe default (Thirsty Crow)
python orchestrate.py --story "..." --out out/mydemo
# story -> reward loop -> harmonize -> Omni synth -> stitch -> consistency enforce
```

**Demo frontend (storybook UI):**
```bash
pip install -r requirements.txt       # includes fastapi + uvicorn
uvicorn web.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
#  Act 1 Narrate  — type a folk tale, watch the agents storyboard it LIVE (SSE)
#  Act 2 Animate  — the pre-baked stitched short plays
#  Act 3 Re-direct— type "make it rainy" / "swap crow for parrot" — LIVE Omni edit
# points at CK_RUN_DIR (default out/crow_video) for the pre-baked short + edit ids
```

## Hackathon-day order of operations (T+0)

1. `python -m common.client` — confirm model IDs (they drift on preview).
2. `video/synth.py smoke_test()` — does the combined `FIRST_FRAME`+`IMAGE_REF`
   call bind refs? measure Omni latency + **actual clip length** (uncontrollable).
   If refs don't bind → set `USE_COMBINED = False` (fallback = keyframe-only i2v).
3. Freeze the seam (`common/schema.py`) — don't change `SelectedFrame` after this.
4. Verify Director structured-output shape (`response_format`); fallback in
   `director.direct_story_fallback` if it errors.

## Non-obvious constraints (baked into the code — see ps_final.md)

- **No frame interpolation** — Omni animates *from* one keyframe forward.
- **No duration control** — `duration_s` is a pacing hint; narration↔video length
  is reconciled in `stitch.reconcile` (freeze-pad, never truncate narration).
- **`store=True`** on every Omni clip — required for re-direction; free-tier
  interactions expire in 1 day.
