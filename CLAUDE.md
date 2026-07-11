# CLAUDE.md — read this first

ChitraKatha: narrate a folk tale → agents storyboard it → NB2 keyframes →
Omni Flash animates a narrated multi-shot short → conversational re-direction.
GDM Bangalore Hackathon, **Idea 4**. Team of 2, each with their own Claude.

**Full spec:** `ps_final.md` (authoritative — supersedes `ps_modified.md`/`ps_orig.md`).
**API cheat-sheet:** `api_ref.md` (call shapes, corrected & verified 2026-07-10).

---

## 1. WHO OWNS WHAT — do not cross this line

There are two people, each with a Claude. The repo is split into two
folder-isolated halves that meet at ONE interface.

| Folder | Owner | Claude works here |
|---|---|---|
| `story/` | **Person 1 (Shreya / teammate)** | Teammate's Claude |
| `video/` | **Person 2 (Shayak)** | Shayak's Claude |
| `common/` | **SHARED — see §2** | Neither edits alone |
| `fixtures/`, `orchestrate.py` | shared / integration | Touch only as noted below |

> **If you are Shayak's Claude:** your folder is **`video/`** (Omni synthesis,
> TTS, stitching, re-direction). Do NOT edit files in `story/`.
>
> **If you are the teammate's Claude:** your folder is **`story/`** (Director,
> Anchor, Keyframe, Critic). Do NOT edit files in `video/`.
>
> If a task seems to need a change in the OTHER folder, STOP and tell your human
> — it's almost certainly a `common/schema.py` change instead (see §2), or a
> misunderstanding of the contract.

Rationale: both halves are built in parallel. If either Claude edits the other's
folder, you get merge conflicts and broken assumptions at integration. Stay in
your lane; talk through the seam.

---

## 2. THE SEAM IS FROZEN — `common/schema.py`

The ONLY thing that crosses the folder boundary is `list[SelectedFrame]`
(defined in `common/schema.py`), serialized to `selected.json` by `common/io.py`.

- `story/` **produces** it: `story/run_story.py` → `out/<run>/selected.json`.
- `video/` **consumes** it: `video/run_video.py` reads it via `common.io.load_selected`.

**Rules for `common/` (schema.py, io.py, client.py):**
1. **Never change `SelectedFrame` fields unilaterally.** Adding/removing/renaming
   a field breaks the other half silently. Both humans must agree first. If your
   task needs a new field, STOP and flag it — propose it, don't commit it.
2. If you must propose a schema change, say so explicitly to your human with the
   exact field and why. Wait for confirmation that the other side is updated too.
3. `client.py` model IDs are env-overridable (`CK_MODEL_*`) — change the env var,
   not the file, when a provisioned ID differs.

Treat `common/` as a contract signed by both teams. Read it; don't rewrite it.

---

## 3. VERIFIED vs UNVERIFIED API shapes (don't "fix" the verified ones)

Shapes were checked against the official cookbook notebooks on 2026-07-10.
`api_ref.md` marks each ✅ (cookbook-proven) or ⚠️ (web-doc-only, smoke-test first).

**✅ Trust these — do NOT rewrite them to match your training data:**
- TTS uses `config=types.GenerateContentConfig(response_modalities=["AUDIO"],
  speech_config=types.SpeechConfig(...))`. NOT `response_format={"type":"audio"}`.
- Image gen uses `response_modalities=["image"]` + `generation_config=
  {"image_config":{"aspect_ratio":...}}`. NOT `response_format={"type":"image"}`.
- Omni bare-image → auto start frame; `store=True` REQUIRED for re-direction.
- Everything runs through `client.interactions.create(...)`, not `generate_content`
  (except the Director structured-output fallback — see below).

**⚠️ Smoke-test on hackathon day BEFORE building on them:**
- **Combined `FIRST_FRAME`+`IMAGE_REF_N` in one Omni call** (`video/synth.py`,
  `USE_COMBINED=True`) — web-doc-only, no cookbook example. Run
  `python -m video.synth` smoke_test first; if refs don't bind, set
  `USE_COMBINED=False` (proven keyframe-only fallback).
- **Director structured output via `response_format`** (`story/director.py`) —
  if it errors, use `direct_story_fallback` (old `generate_content` form, proven).

**Three hard constraints baked into the design (don't design around them):**
1. **No frame interpolation** — Omni animates forward from one keyframe. (Veo does interpolation, not Omni.)
2. **No duration control** — `duration_s` is a pacing HINT. Clip length is whatever
   Omni returns. Narration↔video length is reconciled in `video/stitch.reconcile`
   (freeze-pad, NEVER truncate narration, NEVER time-stretch video).
3. **`store=True`** on every Omni clip (free-tier interactions expire in 1 day).

---

## 4. HOW TO WORK IN PARALLEL (the point of the split)

Neither half waits for the other. Each runs standalone:

**story/ (teammate):**
```bash
python -m story.run_story --story "The Lion and the Mouse" --out out/run1
# deliverable to video/: out/run1/selected.json
```

**video/ (Shayak) — start against the fixture, no story/ needed:**
```bash
python -m fixtures.make_fixture                 # writes fixtures/selected.json (offline stub)
python -m video.run_video --selected fixtures/selected.json --out out/vtest
```

`fixtures/make_fixture.py` writes a valid `selected.json` with placeholder PNGs so
`video/` is fully exercisable (io + stitch logic) without the API key or story/'s
output. Only the live API calls inside synth/narrate need a key.

**Integration (together, at the dry run — build `orchestrate.py` logic then):**
```bash
python orchestrate.py --story "The Lion and the Mouse" --out out/full
```

---

## 5. GIT DISCIPLINE — avoid stepping on each other

- **Commit only files in your own folder** (`story/**` or `video/**`) plus shared
  docs you were asked to touch. Never `git add -A` blindly — you may sweep up the
  other half's WIP or generated media.
- **Never commit** `out/`, `*.mp4`, `*.wav`, `.env`, `.venv/`, or fixture PNGs —
  they're in `.gitignore`; keep it that way.
- **Never commit secrets.** `GEMINI_API_KEY` lives in the environment / a local
  `.env` (gitignored), never in code or committed files.
- **If you must change `common/`,** coordinate first (§2), then make it its own
  small commit with a message saying what seam changed and that both sides agreed.
- Pull before you push; if the other half changed `common/`, re-read the schema
  before continuing.
- Do NOT force-push, do NOT rewrite shared history. Public repo (hackathon rule).

---

## 6. ENVIRONMENT NOTE

Deps are NOT pre-installed in every environment (this scaffold was authored on a
box with no pip). First thing:
```bash
pip install -r requirements.txt          # google-genai>=2.10.0, pydantic, moviepy(+ffmpeg), Pillow
export GEMINI_API_KEY="..."              # from aistudio.google.com/api-keys
python -m common.client                  # confirm all 4 model IDs resolve (they drift on preview)
```
moviepy needs ffmpeg on the system.

---

## 7. HACKATHON-DAY T+0 CHECKLIST (first ~45 min, before deep building)

1. `python -m common.client` — confirm model IDs resolve; set `CK_MODEL_*` env if not.
2. **video/**: `python -m video.synth` smoke_test — does combined FIRST_FRAME+IMAGE_REF
   bind refs? Measure Omni latency + **actual clip length**. Decide `USE_COMBINED`.
3. **story/**: verify `response_format` Director call; fall back if it errors.
4. Confirm the seam (`SelectedFrame`) — freeze it; no changes after this without §2.
5. Latency gate: if one Omni shot > ~90s, start baking the final short by ~T+3h.

Demo plan: Director→Anchor→Keyframe→Critic shown LIVE; final 3-shot short is
PRE-BAKED (Omni is the bottleneck); ONE scripted live re-direction on a short
`store=True` clip; screen-recording fallback. English narration for MVP.
