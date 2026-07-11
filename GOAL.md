# GOAL.md — North Star (read before building, both halves)

> **Purpose:** keep us anchored to the *original* vision and prevent drift into a
> generic "prompt → video" toy or a reskin of the cookbook's
> `Animated_Story_Video_Generation`. If a change doesn't serve the goal below,
> question it.

---

## The one-line goal

> **A folk tale, narrated once, becomes a coherent multi-shot animated short —
> where a verifier-guided agent loop *earns* each keyframe against the story and a
> locked visual identity, and the director can re-shoot any moment by
> conversation.**

The load-bearing, non-generic words:
- **"earns each keyframe"** → a real reward-guided iterative refinement loop
  (NOT best-of-2-and-hope). This is our technical-depth + originality hook.
- **"locked visual identity"** → anchor-conditioned consistency across shots.
- **"re-shoot by conversation"** → true multi-turn Omni re-direction (Idea-4 bar).

## The three novelty claims we must be able to defend

1. **Generation as verifier-guided search, not blind sampling.** Each keyframe is
   scored by an LLM critic on proxy rewards (identity-vs-anchor, prompt adherence,
   composition, narrative correctness) and *iteratively edited* until it clears a
   reward threshold or exhausts a budget. Inspiration: recent work treating
   iterative image editing as a reward-driven (RL/diffusion) process — applied at
   the keyframe level where it's fast (NB2 <4s) and honest.
2. **Storyboard is load-bearing.** The anchor + Critic-selected keyframe *control*
   the video; the storyboard isn't decoration. Kill the keyframe and the pipeline
   has nothing to animate.
3. **Conversational multi-turn re-direction.** "Make shot 2 night" → "now add
   rain" → "zoom on the lion", each chaining on the last, re-stitched into the
   full short. The exact capability Idea-4 rewards.

## What we are NOT (say this out loud to stay honest)

- ❌ NOT a prompt-box-to-video toy.
- ❌ NOT the cookbook `Animated_Story_Video_Generation` (story→image→animate→stitch)
  — that flow is Google's own published baseline. Best-of-2 + one regen is NOT
  enough daylight from it. The **reward loop** is what separates us.
- ❌ NOT claiming MCTS we don't run. We do honest verifier-guided iterative
  refinement (greedy / optional beam over edit trajectories) — deep and real,
  described accurately.

---

## The centerpiece: keyframe reward loop (SPEC — owned by `story/`)

> ⚠️ **Ownership:** this lives in `story/critic.py` + `story/keyframes.py`, which
> belong to Person 1. The `video/` owner does NOT implement this. It is a JOINT
> design decision; this spec is the proposal to build against. Do not change the
> `common/schema.py` seam without both owners agreeing (see CLAUDE.md §2).

**Why feasible:** NB2 image gen is <4s and supports multi-turn *edit* (feed
`previous_interaction_id` or the image + a targeted instruction). Omni video is
the slow/expensive step (~36s) — so we do all the search on IMAGES, then animate
the winner ONCE. Search is cheap exactly where we put it.

**Loop (per beat):**
```
anchor(s) fixed first  →  seed keyframe (NB2, conditioned on anchor)
repeat up to K times (budget):
    reward = Critic(keyframe, anchor, beat)   # LLM judge, structured scores
        axes: identity_vs_anchor, prompt_adherence, composition, narrative_fit  (1–5 each)
    if min(axes) >= THRESHOLD:  break          # earned it
    fix = Critic.targeted_edit(keyframe)       # e.g. "make the mane match the anchor; darken sky"
    keyframe = NB2.edit(keyframe, fix)         # targeted refine, NOT regen-from-scratch
select final keyframe (highest total reward seen)
```

**Upgrades over the current best-of-2 + 1-regen critic:**
1. **Iterate to a reward threshold** (budgeted K, e.g. 3–4), not a single regen.
2. **Targeted NB2 edits** on the same frame (the "iterative editing as a process"
   idea) instead of blind re-sampling.
3. **Explicit proxy-reward rubric** with a threshold — the "on-the-fly reward"
   setup, honestly implemented as an inference-time verifier.
4. *(Optional, if time)* **Beam width B**: keep top-B candidates each round and
   expand each — gives genuine best-first *search* flavor without faking MCTS.

**Demo story:** show the reward trajectory live — "iteration 1 scored 2/5 on
identity → critic said 'mane doesn't match' → NB2 fixed it → iteration 2 scored
4/5 → earned." That narrated loop IS the technical-depth wow.

**Bounds (keep it demo-safe):** hard cap K (never infinite), always keep the
best-seen frame, log every iteration's scores. Same-shape `SelectedFrame` output
to `video/` — the seam does not change.

---

## Status vs. goal (update as we go)

| Piece | Owner | State |
|---|---|---|
| Anchor-conditioned keyframes (identity) | story/ | ✅ proven live — same character holds across scenes |
| **Keyframe reward loop (centerpiece)** | story/ | ✅ built + merged; strict rubric fix (was scoring all 5/5) |
| Global harmonize (cross-beat coherence) | story/ | ✅ built; fixed to pass sibling frame as visual target |
| Director storyboard (auto beat count) | story/ | ✅ verified live |
| Omni synth (keyframe→video, guardrail-resilient) | video/ | ✅ verified live |
| Stitch (native audio, moviepy 2.x) | video/ | ✅ verified live |
| Multi-turn re-direction + element swap + thinking | video/ | ✅ all verified live |
| **Consistency enforcement (typed primitives, Option A)** | video/ | ✅ detection verified; full fix loop wired into pipeline |
| Full end-to-end pipeline (`orchestrate.py`) | both | ✅ one command: story→video→enforce (crow, guardrail-safe) |
| Narration (TTS fallback) | video/ | ✅ wired, off by default (Omni has native audio) |

**Guardrail lesson (verified):** two filters — *violence* (hunter/net/trapped) and
*IP* (cute lion resembles copyrighted characters). Demo story must clear BOTH:
gentle content + distinctly-Indian non-IP characters. The **Thirsty Crow** clears
both end-to-end and is the guardrail-safe demo default in `orchestrate.py`.

**Remaining polish:** the reward loop's critic now discriminates but tends to
score ~4 (tune threshold); harmonize/enforce don't always fully converge in the
bounded rounds (acceptable, demo-safe). 1-min submission video export still TODO.
