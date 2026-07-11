# Problem Statement: ChitraKatha (चित्रकथा) — FINAL / Implementation-Ready

**Track:** Idea 4 — Conversational Video & Motion (Omni Flash), chaining NB2 Lite → Omni Flash
**Team:** 2 people
**Demo story (locked):** *The Lion and the Mouse* (Panchatantra), 3 beats
**Demo language (locked):** English
**Art style (locked):** Amar Chitra Katha (ACK) comic look — instantly recognizable to Indian judges
**One-liner:** Narrate a folk tale; a team of agents storyboards it, generates anchor-consistent keyframes, animates a multi-shot narrated short, then lets you re-direct any shot by conversation.

> *ChitraKatha* literally means "picture-story / storyboard" in Sanskrit — also the name behind India's beloved *Amar Chitra Katha* comics.

> **This doc supersedes `ps_modified.md`.** Every API call shape below is corrected against the official cookbook notebooks (`Get_started_Omni`, `Get_started_TTS`, `Animated_Story_Video_Generation`) and the live docs, verified 2026-07-10. See `api_ref.md` for the shared cheat-sheet (also being corrected).

---

## The Problem

India has the world's richest stock of oral and folk stories — Panchatantra, regional myths, grandmother's tales — but they live in text or memory, not video. Producing even a 30-second animated version needs an artist, an animator, and days of work. "Type a prompt, get a clip" tools produce a single incoherent shot with drifting characters — useless for *storytelling*, which needs consistent characters across multiple shots with cultural specificity. No tool takes "narrate a story" → "coherent multi-shot animated short."

## The Insight

A good animated story isn't one video generation — it's a **directed pipeline**: decompose the narrative into beats, lock a visual identity, render controllable keyframes, then animate *from* those known frames. By using **NB2 Lite keyframes as visual anchors fed into Omni Flash**, we replace blind text→video with **storyboard-conditioned video** — controllable, consistent, and conversationally editable.

> ⚠️ **API-grounded constraints baked into this design:**
> 1. **Frame interpolation is unsupported.** Omni does not "generate video between a first and last frame." Each shot is conditioned on **one starting keyframe (+ optional character/prop references)**, then animated forward. (Interpolation/extension is Veo's job, not Omni's.)
> 2. **Clip duration is NOT a controllable parameter.** There is no duration/length field anywhere in Omni. `[0-Xs]` timecodes only *choreograph content within* a clip; they do not set total length. Therefore `duration_s` in our storyboard is a **pacing hint only**, and narration↔video length is reconciled in post (MoviePy), audio-prioritized.
> 3. **`store=False` disables `previous_interaction_id`.** Any Omni clip we intend to conversationally edit MUST be created with `store=True`.

---

## The System (Multi-Agent)

1. **Director agent (Gemini `gemini-3.5-flash`)** — story + priors → structured storyboard: 3 beats, each `{beat_id, subject, action, setting, camera, motion, duration_s, narration}` + one global `style_spec` + one `character_sheet_prompt` per character/prop. `duration_s` is a **pacing hint** the Director assigns by narrative weight; narration text is written to roughly fit it (~2.5 words/sec), but final sync is done in post.
2. **Anchor generation (NB2 `gemini-3.1-flash-lite-image`)** — **one reference image per character/prop** (Lion, Mouse, + key prop), generated first. *This is the consistency key,* and each maps to an `IMAGE_REF_N` slot in Omni later.
3. **Keyframe agents (parallel fan-out, NB2)** — each beat generates **2 candidate frames**, both conditioned on the relevant anchor image(s) passed as reference images. Fan-out across beats is **parallel** (ThreadPoolExecutor); deliberately no cross-beat continuity check (see Critic).
4. **Critic agent (Gemini `gemini-3.5-flash`) — the bounded "reward" step** — scores the 2 candidates per beat on **prompt-adherence, style-consistency vs. anchor, composition** (all on a **1–5** scale; continuity-vs-neighbor is dropped since fan-out is parallel). Picks the best. **If both candidates score below threshold on any axis → exactly ONE targeted regen for that beat, then pick best-of-whatever-exists. Hard stop, no further loop** (caps worst case at 2× per beat).
5. **Omni Flash synthesis (`gemini-omni-flash-preview`)** — per beat: selected keyframe as **`FIRST_FRAME`** + character/prop anchors as **`IMAGE_REF_N`** *(primary path — see de-risking note)*, plus the Director's motion/camera text with explicit `[0-Xs]` pacing and **"single continuous shot, no scene cuts. No dialogue or voiceover. No text overlay."** `store=True`. Narration (Gemini TTS, English) generated per beat; audio and video reconciled in MoviePy (freeze-pad to `max`, never truncate narration).
6. **Conversational re-direction** — "make shot 2 at night" → new `input` with `previous_interaction_id` = that beat's Omni interaction id → re-synth only that segment. **Scripted live** on a short single-beat clip (see demo plan).

> 🔬 **De-risking step 5 (MANDATORY, first hour):** The combined `FIRST_FRAME` + `IMAGE_REF_N` single-call syntax is documented on the web but has **no cookbook example**. Smoke-test the exact call on the provisioned account before committing. **Written fallback:** plain `image_to_video` with the selected keyframe alone (cookbook-proven, code 28) — the keyframe is already anchor-consistent, so references are redundant for consistency; we lose only extra prop-binding control. Person B owns this test at T+0.

---

## Why It Clears the Idea-4 Bar

- Not a prompt box — keyframe-conditioning makes the storyboard **load-bearing**.
- Uses the **explicitly-encouraged NB2→Omni chain** (even sharing `previous_interaction_id` to hand an NB2 image straight to Omni).
- **Multi-turn conversational orchestration is FIRST-CLASS and SCRIPTED LIVE** (step 6) — the exact capability the track rewards, not stapled on.

## Scoring Fit

| Criteria | Weight | How ChitraKatha wins |
|---|---|---|
| **Creativity & Originality** | 35% | Storyboard-as-prior + bounded verifier-guided keyframe selection is a genuinely novel control scheme. |
| **Live Demo** | 25% | Director → Anchor → Keyframe → Critic shown **live** (NB2 <4s/call); **one scripted live conversational re-direction** on a short clip; the polished 3-shot short is **pre-baked** (Omni synthesis is the latency bottleneck). |
| **Impact in India** | 25% | Regional-language cultural storytelling / folk-tale preservation. English for this MVP; Gemini TTS auto-detects language, so Hindi/Kannada/Tamil is a zero-integration future step (say this to judges). |
| **Technical Depth** | 15% | Anchor-conditioned consistency + bounded verifier loop + native stateful segment re-synthesis via `previous_interaction_id`. |

---

## Locked Scope (3-Beat MVP)

- **Must-have:** Director → per-character anchors → 2-candidate keyframes/beat (Critic, ≤1 regen/beat) → Omni video/beat → stitched 3-shot short with English narration, for *The Lion and the Mouse*. ACK style, polished end-to-end. **Pre-baked** final short is the safety net.
- **Must-have (demo):** ONE **scripted live** conversational re-direction of a short clip (`store=True`), with a screen-recording fallback.
- **Nice-to-have:** second art style; a pre-baked Hindi-narrated version of the same short as an "impact" flourish.
- **Cut first if time's tight:** the regen step (fall back to "always pick best of 2, no regen") before cutting anything else.

---

## Architecture

```
User prompt + priors (style=ACK, characters, language=EN)
        │
   [1] DIRECTOR (gemini-3.5-flash, structured output)
        → storyboard: 3 beats, each
          {beat_id, subject, action, setting, camera, motion,
           duration_s (pacing hint), narration}
          + global style_spec + character_sheet_prompt[]
        │
   [2] ANCHOR gen (NB2 gemini-3.1-flash-lite-image):
        ONE image PER character/prop (Lion, Mouse, +prop)
        │
   [3] KEYFRAME agents (parallel across 3 beats, NB2):
        beat_i → 2 candidates, each conditioned on relevant anchor(s)
        │
   [4] CRITIC (gemini-3.5-flash): score 2 cands on
        {prompt_adherence, style_consistency, composition} 1–5
        → pick best; if any axis < threshold on both cands:
          1 targeted regen → pick best-of-existing (HARD STOP)
        │
   [5] OMNI FLASH per beat (store=True):
        input = [ FIRST_FRAME=selected keyframe,
                  IMAGE_REF_0..N=character/prop anchors,   ← smoke-test; fallback = keyframe only
                  text = motion + [0-Xs] pacing
                         + "single continuous shot, no scene cuts.
                            No dialogue or voiceover. No text overlay." ]
        → per-beat narration (TTS gemini-3.1-flash-tts-preview, EN)
        → reconcile: beat_clip.duration = max(video, audio);
          freeze-pad the shorter, NEVER truncate narration,
          NEVER time-stretch. video.set_audio(narration).
        │
   Stitch 3 beat_clips (MoviePy concatenate) → final short   ← PRE-BAKED, shown in demo
        │
   Re-direction (SCRIPTED LIVE, short clip):
   "make shot 2 at night" → new input
     + previous_interaction_id of that beat's Omni call
   → re-synth only that segment.  (fallback: screen recording)
```

---

## The A↔B Data Contract (freeze this in hour one)

Person A produces, per beat, exactly this object; Person B consumes it. Nothing else crosses the seam.

```python
# One per beat, produced by the story pipeline (A), consumed by synthesis (B)
{
  "beat_id": int,                 # 0,1,2
  "selected_keyframe_b64": str,   # PNG base64, the Critic's winner
  "anchor_b64s": list[str],       # ordered PNGs → become IMAGE_REF_0..N
  "motion_text": str,             # A concatenates: action + ". " + camera + ". " + motion
  "duration_s": float,            # pacing hint only
  "narration": str,               # English narration line for this beat
}
```

- `motion_text` is **built by A** (the Director owns `action`/`camera`/`motion` fields; A concatenates them). B does not re-derive it.
- `anchor_b64s` order is fixed by A and documented per beat (e.g. `[lion, mouse]`), so B's `IMAGE_REF_0`=lion, `IMAGE_REF_1`=mouse in the prompt text.
- Handoff medium for the dry run: a `list[dict]` in a shared module, or a JSON file on disk. Decide at the dry run; the schema does not change either way.

---

## Task Split (2 people)

- **Person A — Story pipeline (Director → Anchor → Keyframe → Critic).** Owns: storyboard Pydantic schema, per-character anchor generation, NB2 candidate fan-out (ThreadPoolExecutor), Critic rubric + threshold + single-regen logic. Produces the A↔B object. This is the live-on-stage half.
- **Person B — Synthesis + assembly.** Owns: **the T+0 combined-call smoke test**, Omni prompting (`FIRST_FRAME`/`IMAGE_REF_N` wiring or fallback), `store=True`, TTS narration, the MoviePy reconciliation + stitch, the pre-baked final short, and the scripted re-direction path. Also owns **the 1-min submission demo video export**.
- **Shared, hour one:** Person A inits the **public GitHub repo** (rules require public); both sit together for the **first full end-to-end dry run** — the one point where both halves meet.

---

## Timeline (10:30 begin → 5:00 submit)

| Time | A | B | Joint |
|---|---|---|---|
| **T+0 (first 45 min)** | Verify model IDs via `models.list()`; init public repo; Director skeleton | **Smoke-test combined FIRST_FRAME+IMAGE_REF call**; decide primary vs fallback path; **measure Omni latency/clip length** | Freeze A↔B contract |
| **T+0** (∥) | 10-min ACK style check on Lion anchor (confirm it renders; don't rabbit-hole) | | |
| **T+1.5h** | Anchors + keyframe fan-out working | image_to_video working end-to-end for 1 beat | |
| **T+3h** | Critic + regen bounded loop | TTS + MoviePy reconcile + stitch | **Full E2E dry run** (measure total wall-clock) |
| **T+4.5h** | polish Critic thresholds | **Pre-bake the final 3-shot short**; build scripted re-direction clip (store=True) | |
| **T+5.5h** | | | Rehearse live demo + record fallback screencap |
| **~T+6h** | | **Export 1-min submission video** | Submit; confirm repo public + all members added |

> **Latency gate (from B's T+0 measurement):** if one Omni shot takes > ~90s under hackathon load, start baking the final short **by T+3h**, not last-minute.

---

## Corrected API shapes (the ones `ps_modified.md` / `api_ref.md` got wrong)

**TTS (was wrong):** use `config` with `SpeechConfig`, not `response_format={"type":"audio"}`.
```python
from google.genai import types
it = client.interactions.create(
    model="gemini-3.1-flash-tts-preview",
    input=beat["narration"],
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore"))),
    ),
)
# audio bytes live in interaction.steps[].content[].inline_data (see cookbook helper)
```

**Omni image-to-video (primary — combined; smoke-test first):**
```python
it = client.interactions.create(
    model="gemini-omni-flash-preview",
    input=[
        {"type":"image","data": keyframe_b64, "mime_type":"image/png"},   # FIRST_FRAME
        {"type":"image","data": lion_b64,     "mime_type":"image/png"},   # IMAGE_REF_0
        {"type":"image","data": mouse_b64,    "mime_type":"image/png"},   # IMAGE_REF_1
        {"type":"text","text":
          "[# Sources <FIRST_FRAME>@Image1] [# References <IMAGE_REF_0>@Image2 <IMAGE_REF_1>@Image3] "
          "<IMAGE_REF_0> the lion sleeps; <IMAGE_REF_1> the mouse scurries across. "
          "[0-5s] slow push-in. Single continuous shot, no scene cuts. "
          "No dialogue or voiceover. No text overlay."},
    ],
    generation_config={"video_config": {"task": "image_to_video"}},
    store=True,                       # REQUIRED for later re-direction
    response_format={"type":"video","aspect_ratio":"16:9"},
)
```
**Fallback (cookbook-proven) if smoke test fails:** drop the `IMAGE_REF` images and tags, keep just `[keyframe_image, motion_text]`.

**Re-direction (scripted live):**
```python
edit = client.interactions.create(
    model="gemini-omni-flash-preview",
    previous_interaction_id=beat_omni_interaction.id,   # from a store=True call
    input="Make it night time. Keep everything else the same.",
)
```

**MoviePy reconciliation (authoritative rule):**
```python
v = VideoFileClip(beat_mp4); a = AudioFileClip(beat_wav)
dur = max(v.duration, a.duration)
if v.duration < dur:                       # freeze last frame to fill; never stretch
    v = concatenate_videoclips([v, ImageClip(v.get_frame(v.duration-0.04)).set_duration(dur - v.duration)])
clip = v.set_audio(a).set_duration(dur)    # narration always plays in full
```

---

## Resolved Open Decisions (were open in `ps_modified.md`)

1. **Art style** → **locked: Amar Chitra Katha comic.** 10-min sanity render at T+0, but no bake-off rabbit hole.
2. **Critic threshold** → start at **regen if either candidate scores < 3/5 on any axis**; tune after seeing the first beat's real scores.
3. **Latency dry run** → owned by Person B at T+0 (also measures actual clip length, since duration is uncontrollable). Gates when the final short must be baked.
4. **Demo language** → **English** (Hindi version is a pre-baked nice-to-have, not on the critical path).
5. **Re-direction** → **scripted live** on a short `store=True` clip, screencap fallback.
6. **Synthesis path** → **combined FIRST_FRAME+IMAGE_REF primary**, keyframe-only `image_to_video` fallback, decided by the T+0 smoke test.

---

## Submission checklist (hard requirements from the participant guide)

- [ ] Public GitHub repo (A, T+0).
- [ ] 1-minute demo video highlighting only what was built today (B, ~T+6h).
- [ ] All team members added on the submission page.
- [ ] Demo link accessible; repo public re-verified before 5:00 PM.
