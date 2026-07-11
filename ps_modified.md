# Problem Statement: ChitraKatha (चित्रकथा)

**Track:** Idea 4 — Conversational Video & Motion (Omni Flash), chaining NB2 Lite → Omni Flash
**Team:** 2 people
**Demo story (locked):** *The Lion and the Mouse* (Panchatantra), 3 beats, English narration

**One-liner:** Speak a story in any Indian language; a team of agents storyboards it, generates consistent keyframes, and animates a multi-shot narrated short — then lets you re-direct any shot by conversation.

> *ChitraKatha* (चित्रकथा) literally means "picture-story / storyboard" in Sanskrit — also the name behind India's beloved *Amar Chitra Katha* comics.

---

## The Problem

India has the world's richest stock of oral and folk stories — Panchatantra, regional myths, grandmother's tales — but they live in text or memory, not video. Producing even a 30-second animated version needs an artist, an animator, and days of work. Meanwhile "type a prompt, get a clip" tools produce a single incoherent shot with drifting characters — useless for actual *storytelling*, which needs consistent characters across multiple shots, in a regional language, with cultural specificity. No tool takes "narrate a story" → "coherent multi-shot animated short."

## The Insight

A good animated story isn't one video generation — it's a **directed pipeline**: decompose the narrative into beats, lock a visual identity, render controllable keyframes, then animate *from* known frames. By using **NB2 Lite keyframes as visual anchors** (fed into Omni Flash as `FIRST_FRAME` + `IMAGE_REF_N` character/style references), we replace blind text→video with **storyboard-conditioned video** — controllable, consistent, and conversationally editable.

> ⚠️ **Corrected from earlier draft:** Omni Flash does **not** support frame interpolation ("generating video between a first and last frame" is explicitly unsupported). The pipeline conditions each shot on **one selected keyframe as the starting frame, plus character/prop reference images**, not a begin/intermediate/end triplet.

## The System (Multi-Agent)

1. **Director agent (Gemini)** — takes the story + priors (style, language, characters) → structured storyboard: 3 beats, each with `{beat_id, subject, action, setting, camera, duration_s, narration_line}`, plus one global `style_spec`. **Duration is decided by the Director per beat** (based on narrative weight), fixed *before* narration is generated, so narration text is written to fit the beat's runtime rather than the other way around.
2. **Anchor generation (NB2)** — **one reference image per character/prop** (not a single composite sheet), generated first. *This is the consistency key,* and it maps directly onto Omni Flash's `IMAGE_REF_N` slots later.
3. **Keyframe agents (parallel fan-out, NB2)** — each beat generates **2 candidate frames**, both conditioned on the relevant anchor image(s) via NB2's multi-image edit mode. Fan-out across beats is **parallel** — there is deliberately no cross-beat continuity check (see Critic, below); this trades a small amount of visual continuity for speed and pipeline simplicity.
4. **Critic agent (Gemini) — the "reward" step** — scores the 2 candidates per beat on **prompt-adherence, style-consistency vs. anchor, and composition** (continuity-with-neighbors is dropped, since fan-out is parallel and there's no guaranteed "prior selected frame" to compare against at score time). Picks the best candidate, or — **if both candidates score below threshold — issues exactly one targeted regen** per beat. No further regen after that; whichever frame scores highest after the regen is used, even if imperfect. This caps worst-case Critic-loop time at 2× per beat.
5. **Omni Flash synthesis** — selected keyframe as `FIRST_FRAME`, character/prop anchors as `IMAGE_REF_N`, plus the Director's motion/camera description and `duration_s`, explicitly stated in-prompt (e.g. `[0-6s] ...`) with a "single continuous shot, no scene cuts" instruction to prevent Omni Flash from inventing its own internal cuts. Narration audio (Gemini TTS, English) is generated per beat and overlaid.
6. **Conversational re-direction** — "make shot 2 at night" → re-sent as a follow-up `input` with `previous_interaction_id` pointing at that beat's last Omni Flash generation, so only that segment is re-synthesized. **Built, but not part of the scripted demo** — shown live only if time allows after the MVP is solid.

## Why It Clears the Idea-4 Bar

- Not a prompt box — keyframe-conditioning makes the storyboard **load-bearing**.
- Uses the **explicitly-encouraged NB2→Omni chain**.
- **Multi-turn conversational orchestration** (step 6, native to Omni Flash's `previous_interaction_id`) and **element swapping** are first-class, not stapled on.

## Scoring Fit

| Criteria | Weight | How ChitraKatha wins |
|---|---|---|
| **Creativity & Originality** | 35% | Storyboard-as-prior + verifier-guided keyframe selection is a genuinely novel control scheme. |
| **Live Demo** | 25% | Director → Anchor → Keyframe → Critic loop shown **live** (NB2 is <4s/call); the Omni Flash video synthesis step uses the **pre-baked final clips**, since video generation time is the pipeline's real bottleneck and not worth risking on stage. |
| **Impact in India** | 25% | Regional-language cultural storytelling / folk-tale preservation — every language, every region (English for this MVP; multi-language is future work). |
| **Technical Depth** | 15% | Anchor-conditioned consistency + bounded verifier loop + segment-level re-synthesis via native stateful editing. |

## Locked Scope (3-Beat MVP)

- **Must-have:** Director → per-character anchors → 2-candidate keyframes per beat (Critic, ≤1 regen/beat) → Omni Flash video per beat (`FIRST_FRAME` + `IMAGE_REF_N`, explicit duration, single-shot instruction) → stitched 3-shot short with English narration, for *The Lion and the Mouse*. One art style, polished end-to-end.
- **Should-have:** conversational re-direction of one shot, working but demoed opportunistically, not scripted.
- **Nice-to-have:** second language, second art style.
- **Cut first if time's tight:** the regen step itself (fall back to "always pick best of 2, no regen") before cutting anything else.

---

## Architecture

```
User prompt + priors (style, characters, language=EN)
        │
   [1] DIRECTOR agent (Gemini)
        → structured storyboard: 3 beats, each with
          {subject, action, setting, camera, duration_s, narration_line}
          + GLOBAL style spec
        │
   [2] ANCHOR gen (NB2): ONE reference image PER character/prop
        (Lion, Mouse, + any key prop) — not a composite sheet
        │
   [3] KEYFRAME agents (parallel fan-out across all 3 beats, NB2)
        → beat_i → 2 candidates, conditioned on relevant anchor image(s)
          via NB2 multi-image edit
        │
   [4] CRITIC agent (Gemini) ← bounded reward step
        → scores 2 candidates on {prompt-adherence, style-consistency
          vs anchor, composition}
        → picks best, OR if both below threshold: 1 targeted regen,
          then picks best of whatever exists (hard stop, no further loop)
        │
   [5] OMNI FLASH per beat:
        FIRST_FRAME = selected keyframe
        IMAGE_REF_N = character/prop anchors
        prompt = motion + camera description + explicit duration_s
                 + "single continuous shot, no scene cuts"
        → narration (Gemini TTS, EN) generated to fit duration_s,
          overlaid on the clip
        │
   Stitch 3 shots → final short (THIS is what's shown live in the demo)
        │
   Conversational edit loop (built, opportunistic demo only):
   "make shot 2 at night" → new input + previous_interaction_id
   of that beat's last Omni Flash call → re-synth only that segment
```

## Task Split (2 people)

- **Person A — Story pipeline (Director → Anchor → Keyframe → Critic):** owns the storyboard schema, per-character anchor generation, NB2 candidate generation, and the Critic rubric/regen logic. This is what's shown live on stage.
- **Person B — Video synthesis + assembly:** owns Omni Flash prompting (FIRST_FRAME/IMAGE_REF_N wiring, duration/single-shot instructions), TTS narration + duration-fit logic, stitching the 3 shots, and the pre-baked fallback video. Also owns the conversational re-direction stretch goal once the MVP path is solid.

Both should sit together for the first live end-to-end dry run (see below) since that's the one point where both halves of the pipeline meet.

## Open Decisions Still Needing a Quick Test (do these first, not last)

1. **Art style** — you chose to decide after seeing NB2 test outputs. First task of the hackathon: generate 2-3 style tests (Amar Chitra Katha comic, Madhubani, one more if time) of the Lion anchor, pick fast, move on. Don't let this become a rabbit hole.
2. **Critic score threshold for regen** — needs an actual number (e.g. "regen if either axis scores <3/5"). Pick a rough value, adjust once you see real Critic outputs on the first beat.
3. **End-to-end latency dry run** — run the *entire* pipeline once, for real, in the first hour, specifically to measure how long Omni Flash synthesis takes per shot under hackathon API load. This number determines how early you need to start baking the final demo video and whether "pre-baked Omni step" needs to happen well before the demo slot, not last-minute.