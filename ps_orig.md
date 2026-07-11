# Problem Statement: ChitraKatha (चित्रकथा)

**Track:** Idea 4 — Conversational Video & Motion (Omni Flash), chaining NB2 Lite → Omni Flash

**One-liner:** Speak a story in any Indian language; a team of agents storyboards it, generates consistent keyframes, and animates a multi-shot narrated short — then lets you re-direct any shot by conversation.

> *ChitraKatha* (चित्रकथा) literally means "picture-story / storyboard" in Sanskrit — also the name behind India's beloved *Amar Chitra Katha* comics.

---

## The Problem

India has the world's richest stock of oral and folk stories — Panchatantra, regional myths, grandmother's tales — but they live in text or memory, not video. Producing even a 30-second animated version needs an artist, an animator, and days of work. Meanwhile "type a prompt, get a clip" tools produce a single incoherent shot with drifting characters — useless for actual *storytelling*, which needs consistent characters across multiple shots, in a regional language, with cultural specificity. No tool takes "narrate a story" → "coherent multi-shot animated short."

## The Insight

A good animated story isn't one video generation — it's a **directed pipeline**: decompose the narrative into beats, lock a visual identity, render controllable keyframes, then animate *between* known frames. By using **NB2 Lite keyframes as visual priors** (begin / intermediate / end frames) fed into **Omni Flash**, we replace blind text→video with **storyboard-conditioned video** — controllable, consistent, and conversationally editable.

## The System (Multi-Agent)

1. **Director agent** — takes the user's spoken/typed story + priors (style: "Amar Chitra Katha comic" / "Madhubani" / "anime"; language; characters) → structured storyboard: N beats, each `{subject, action, setting, camera}` + one global style spec.
2. **Anchor generation (NB2)** — one character/style reference sheet, generated first. *This is the consistency key.*
3. **Keyframe agents (parallel fan-out, NB2)** — each beat generates 2–3 candidate frames, **all conditioned on the anchor** so character/style don't drift.
4. **Critic agent (Gemini) — the "reward" step** — scores candidates on prompt-adherence, style-consistency vs. anchor, composition, and continuity with neighboring frames; picks the best or issues one targeted regen. *(Honest inference-time verifier-guided selection — best-of-N, not MCTS.)*
5. **Omni Flash synthesis** — selected keyframes as begin/intermediate/end priors + motion descriptions → animated shots, stitched into the short with narration (Gemini TTS in the chosen language).
6. **Conversational re-direction** — "make shot 2 at night," "swap the tiger for a lion" → re-runs *only* that segment. This is the multi-turn editing the Idea-4 bar demands.

## Why It Clears the Idea-4 Bar

- Not a prompt box — keyframe-conditioning makes the storyboard **load-bearing**.
- Uses the **explicitly-encouraged NB2→Omni chain**.
- **Multi-turn conversational orchestration** (step 6) and **element swapping** are first-class, not stapled on.

## Scoring Fit

| Criteria | Weight | How ChitraKatha wins |
|---|---|---|
| **Creativity & Originality** | 35% | Storyboard-as-prior + verifier-guided keyframe selection is a genuinely novel control scheme. |
| **Live Demo** | 25% | Show Director + keyframe + critic loop **live** (NB2 is <4s); pre-render one final video as latency insurance. |
| **Impact in India** | 25% | Regional-language cultural storytelling / folk-tale preservation — every language, every region. |
| **Technical Depth** | 15% | Anchor-conditioned consistency + verifier loop + segment-level re-synthesis. |

## 6.5-Hour Scope

- **Must-have (MVP):** Director → anchor → keyframes (best-of-N critic) → Omni video for a 3–4 beat story in 1 language + 1 style. One pre-baked demo story polished end-to-end.
- **Should-have:** conversational re-direction of one shot.
- **Nice-to-have:** second language, second art style, narrated audio.
- **Cut first if time's tight:** the outer video-level critic (step 6 loop); keep only keyframe-level best-of-N.

---

## Architecture

```
User prompt + priors (style, ref images, language)
        │
   [1] DIRECTOR agent (Gemini)
        → structured storyboard: N beats, each with
          {subject, action, setting, camera} + GLOBAL style spec
        │
   [2] ANCHOR gen (NB2): one character/style reference image
        │
   [3] KEYFRAME agents (parallel fan-out, all conditioned on ANCHOR)
        → beat_i → NB2 generates 2-3 candidates
        │
   [4] CRITIC agent (Gemini)  ← the "reward" step, done honestly
        → scores candidates on {prompt-adherence, style-consistency
          vs anchor, composition, continuity w/ neighbors}
        → picks best OR issues a targeted edit prompt → regen
        │
   [5] OMNI FLASH: selected keyframes as begin/intermediate/end
        priors + motion descriptions → video
        │
   [6] (bounded) OUTER CRITIC: Gemini watches the video, scores
        temporal consistency, regenerates ONE weak keyframe → re-synth
        │
   Conversational edit loop: "make shot 2 at night" → re-run only that segment
```

---

## Open Decisions

1. **Story scope:** folk tales/mythology only (tight, culturally strong), or *any* user story (broader, but demo needs a crisp example)? *Lean: build for any, demo a folk tale.*
2. **Input modality:** typed story, or *spoken* (voice input)? Voice adds India-accessibility punch but costs integration time. *Lean: typed for MVP, voice as nice-to-have.*
3. **Art style for the demo:** which single style do we polish? Amar Chitra Katha comic look is instantly recognizable to Indian judges. *Lean: ACK comic.*
