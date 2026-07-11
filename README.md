# ChitraKatha (चित्रकथा)

**Narrate a folk tale → a team of agents storyboards it, *earns* each keyframe with a
verifier-guided reward loop, animates a multi-shot narrated short, then lets you
re-direct any shot by conversation.**

GDM Bangalore Hackathon — **Idea 4** (Conversational Video & Motion), chaining
**NB2 Lite** (ultra-fast image gen) → **Omni Flash** (conversational video).

> *ChitraKatha* means "picture-story / storyboard" in Sanskrit — also the name behind
> India's beloved *Amar Chitra Katha* comics, the locked visual style.

North star: [`GOAL.md`](GOAL.md) · Full spec: [`ps_final.md`](ps_final.md) ·
API cheat-sheet: [`api_ref.md`](api_ref.md)

---

## What it does

1. **Director** turns a folk tale into a structured storyboard (chooses beat count from
   the story; each beat = subject/action/setting/camera/motion/narration).
2. **Anchors** — one reference image per character/prop (NB2). *The consistency key.*
3. **Keyframe fan-out** — 2 candidates per beat, conditioned on the anchors (NB2).
4. **Verifier-guided reward loop** — an LLM critic scores each keyframe on 5 proxy-reward
   axes (prompt-adherence, style, identity-vs-anchor, composition, narrative-fit); if the
   weakest axis is below threshold it issues a targeted edit and re-scores, up to a bounded
   budget — the keyframe is *earned*, not sampled-and-hoped. (`story/critic.py`)
5. **Global harmonize** — judges all winning keyframes together, re-generates the single
   outlier to match the set's palette/look (sibling frame passed as the visual target).
6. **Omni synthesis** — each keyframe → an animated shot (Omni image-to-video, `store=True`),
   guardrail-resilient (a blocked beat retries then skips, never crashes the run).
7. **Narration** — Gemini TTS of each beat's line, mixed *over Omni's own ambient audio*
   (ducked bed + narration foreground).
8. **Stitch** → one short (moviepy).
9. **Consistency enforcement** — samples rendered frames, checks them against **typed,
   anchor-derived JSON primitives** (per identity feature), and auto re-directs any beat
   that drifts. (`video/consistency.py`)
10. **Conversational re-direction** — "make it rainy", "swap the crow for a parrot" — a
    stateful multi-turn session edits/chains via Omni `previous_interaction_id` and
    re-stitches, with an art-style lock so edits don't drift out of the comic look.

**The novelty (defensible to judges):** generation as *verifier-guided search*, not blind
sampling; a *typed consistency contract* enforced across the timeline; and genuine
*multi-turn conversational editing* — the Idea-4 bar.

---

## Architecture — two folder-isolated halves + a web layer

```
common/          shared contract (imported by both halves; the FROZEN seam)
  schema.py        Pydantic models — SelectedFrame is the story→video seam
  client.py        genai client + model IDs (+ dotenv) + `python -m common.client` check
  io.py            save/load selected.json (+ PNG sidecars)

story/  (Person 1) Director → Anchor → Keyframe → reward-loop Critic → harmonize
  run_story.py     CLI: story text → out/<run>/selected.json
  critic.py        the verifier-guided reward loop + global harmonize
  style.py         the locked Amar Chitra Katha visual contract (+ anti-text/border)
  inspect_run.py   debug: saves every candidate + an index.html to eyeball the pipeline

video/  (Person 2) Omni synth → narration → stitch → consistency enforce → re-direction
  run_video.py     CLI: selected.json → chitrakatha.mp4  (--narrate --mix --enforce)
  synth.py         Omni image_to_video (store=True); guardrail retry+skip; --think reasoning
  narrate.py       Gemini TTS
  stitch.py        moviepy 2.x assembly; narration-over-ducked-Omni mix
  consistency.py   typed JSON primitive derivation + per-field check + auto re-direct
  redirect.py      multi-turn RedirectSession: edit / swap_element (style-locked)
  ab_demo.py       naive text→video vs ChitraKatha, side-by-side (demo device)

web/             FastAPI demo frontend (storybook UI)
  server.py        /api/direct (SSE story) · /api/animate (SSE synth+narrate) ·
                   /api/run · /api/redirect (edit/swap)
  static/          index.html · app.js · style.css  (3-act storybook, no build step)

orchestrate.py   full pipeline in one command (story → video → enforce)
```

**The only object that crosses the story↔video seam is `list[SelectedFrame]`**
(`common/schema.py`), serialized as `selected.json`. Neither half imports the other.

---

## Setup

```bash
pip install -r requirements.txt          # google-genai, pydantic, moviepy(+ffmpeg), Pillow, fastapi, uvicorn
export GEMINI_API_KEY="..."              # or put it in .env (auto-loaded)
python -m common.client                  # confirm all model IDs resolve (they drift on preview)
```
Requires **ffmpeg** on the system (moviepy).

---

## Run it

**Full pipeline, one command:**
```bash
python orchestrate.py                    # guardrail-safe default (The Thirsty Crow)
python orchestrate.py --story "..." --out out/mydemo
python orchestrate.py --no-enforce       # skip the consistency net (faster)
```

**Demo frontend (the storybook UI):**
```bash
uvicorn web.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
#   Act I  Narrate   — type a folk tale; watch the agents storyboard it + earn keyframes LIVE (SSE)
#   Act II Animate   — the story is synthesized through Omni LIVE, per-beat, with narration
#   Act III Re-direct— "make it rainy" / "swap the crow for a parrot" — LIVE Omni edit, re-stitched
```

**Each half standalone:**
```bash
python -m story.run_story --story "The Thirsty Crow ..." --out out/run1   # → selected.json
python -m video.run_video --selected out/run1/selected.json --out out/run1 --narrate --mix --enforce
python -m story.inspect_run --story "..." --out inspect/run1              # visual pipeline debug
```

**Conversational re-direction (CLI):**
```bash
python -m video.redirect --run out/run1                 # interactive REPL (edit/editx/swap/script)
python -m video.redirect --run out/run1 --swap crow "green parrot"
```

---

## Hard-won constraints (verified live — baked into the code)

- **Omni `image_to_video` takes exactly ONE image** — consistency rides on the (anchor-
  conditioned) keyframe; extra characters go in the text prompt. (`reference_to_video` takes
  many but re-imagines the scene — not our path.)
- **Omni generates its OWN audio** — we keep it as the ambient bed and mix TTS narration on top.
- **No duration control** — `duration_s` is a pacing hint; clip length (~5–10s) is whatever
  Omni returns. Narration↔video reconciled in `stitch.reconcile` (freeze-pad, never truncate).
- **`store=True`** on every Omni clip — required for re-direction; free-tier interactions expire ~1 day.
- **TWO guardrails** — *violence* (hunter/net/trapped) AND *IP* (a cute lion resembles
  copyrighted characters). The demo story must clear BOTH → the **Thirsty Crow** does
  (no violence, a crow resembles no IP). Distinct Indian art style also lowers IP risk.
- **Pin the art style on every edit/swap** or Omni drifts to 3D/Pixar/googly-eye.

Models used: `gemini-3.5-flash` (text/critic),
`gemini-3.1-flash-lite-image` (NB2), `gemini-omni-flash-preview` (video),
`gemini-3.1-flash-tts-preview` (narration).
