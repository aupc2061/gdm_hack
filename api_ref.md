# ChitraKatha — Gemini API Implementation Reference

Compiled from official Gemini API docs (ai.google.dev) + cookbook. This is the technical cheat-sheet for building the pipeline. Verify all model IDs against the temporary accounts provisioned on hackathon day — preview model names drift.

---

## 0. The Big Picture: everything runs through the **Interactions API**

The new stack replaces `generate_content` with `client.interactions.create(...)`. One uniform call shape for **text, image, video, audio, structured output, and multi-turn**. This is a huge win for us — the *same* primitive powers every agent in our pipeline, and `previous_interaction_id` gives us free conversational state (our step-6 re-direction loop).

```python
from google import genai
client = genai.Client()

interaction = client.interactions.create(
    model="gemini-3.5-flash",
    input="...",                 # str OR list of typed parts
)
print(interaction.output_text)
```

**Setup**
```bash
pip install -U "google-genai>=2.10.0"   # >=2.10 needed for Omni video_config "task"; TTS needs >=2.9
export GEMINI_API_KEY="YOUR_API_KEY"    # from aistudio.google.com/api-keys
```

> ✅ **Verified 2026-07-10** against cookbook notebooks `Get_started_Omni`, `Get_started_TTS`, `Animated_Story_Video_Generation`. Shapes below marked ✅ are cookbook-confirmed; ⚠️ marks web-doc-only (no cookbook example — smoke-test first).

**Input parts** (list form): each part is a dict with a `type`:
- `{"type": "text", "text": "..."}`
- `{"type": "image", "data": <base64>, "mime_type": "image/png"}` — or `"uri": "..."` instead of `data`
- `{"type": "document", "uri": file.uri}` — for uploaded video/files

**Output accessors:** `interaction.output_text`, `interaction.output_image.data`, `interaction.output_video.data`, `interaction.output_audio.data` (all base64 where binary).

**Multi-turn:** pass `previous_interaction_id=interaction.id`. Model auto-preserves reasoning/context across turns — no manual history threading.

> ⚠️ **`store=False` DISABLES `previous_interaction_id`.** (Docs, verbatim: "store=false prevents using previous_interaction_id for subsequent turns.") So any interaction you intend to edit later — including every Omni clip we might re-direct — MUST be created with `store=True`. Free-tier retention is **1 day**, paid 55; a clip baked on a prior day is NOT editable live.

**Generation config gotchas (NEW API):**
- Use `generation_config={"thinking_level": "minimal|low|medium|high"}` (default medium).
- **Do NOT use** `temperature`, `top_p`, `top_k`, or numeric `thinking_budget` — deprecated/unsupported.

---

## 1. DIRECTOR agent — story → structured storyboard

Structured output via `response_format` with a JSON schema (Pydantic `.model_json_schema()` or a TypedDict).

> ⚠️ **Exact structured-output shape on the Interactions API is not cookbook-confirmed here** — the animated-story cookbook used the OLD `generate_content(config={'response_mime_type':'application/json','response_schema':...})`. The `response_format` form below is web-doc-derived. **Verify at T+0** with a trivial 1-beat call; if it errors, fall back to the `generate_content` config form (that one is cookbook-proven).

```python
from pydantic import BaseModel, Field
from typing import List

class Beat(BaseModel):
    subject: str = Field(description="Who/what is in frame")
    action: str = Field(description="What happens in this beat")
    setting: str = Field(description="Location/time/mood")
    camera: str = Field(description="Shot type + movement")
    image_prompt: str = Field(description="Full NB2 prompt for the keyframe")
    narration: str = Field(description="Voiceover line for this beat")

class Storyboard(BaseModel):
    global_style: str = Field(description="One style spec applied to ALL beats")
    character_sheet_prompt: str = Field(description="Prompt for the anchor reference image")
    beats: List[Beat]

interaction = client.interactions.create(
    model="gemini-3.5-flash",
    input=f"Turn this story into a {N}-beat animated storyboard. Story: {user_story}. "
          f"Style: {style}. Language: {language}. Keep the character visually identical across beats.",
    response_format={
        "type": "text",
        "mime_type": "application/json",
        "schema": Storyboard.model_json_schema(),
    },
)
board = Storyboard.model_validate_json(interaction.output_text)
```

---

## 2. ANCHOR generation — NB2 Lite (the consistency key)

**Image model IDs** (Nano Banana family):
- `gemini-3.1-flash-lite-image` — **fastest/cheapest → use for keyframe fan-out & candidates**
- `gemini-3.1-flash-image` — versatile; supports 512px/1K/2K/4K
- `gemini-3-pro-image` — premium/complex
- Generate ONE anchor (character/style reference sheet) first from `board.character_sheet_prompt`.

✅ **Cookbook-confirmed shape** (`Get_started_Omni` code 26): use `response_modalities=["image"]` + `generation_config={"image_config": {"aspect_ratio": ...}}`. **NOT** `response_format={"type":"image","image_size":...}` (that was wrong in the earlier draft). `interaction.output_image` convenience prop exists; `.data` may be base64 str or bytes — handle both.
```python
import base64

def gen_image(prompt, refs=None, model="gemini-3.1-flash-lite-image", ar="16:9"):
    parts = [{"type": "text", "text": prompt}]
    for r in (refs or []):
        parts.append({"type": "image", "data": r, "mime_type": "image/png"})
    it = client.interactions.create(
        model=model,
        input=parts,
        response_modalities=["image"],
        generation_config={"image_config": {"aspect_ratio": ar}},
    )
    part = it.output_image
    return part.data   # base64 PNG str (or bytes — base64.b64decode() if str)

anchor_b64 = gen_image(board.character_sheet_prompt)
```

---

## 3. KEYFRAME agents — parallel fan-out, ALL conditioned on anchor

Pass the anchor as a reference image so character/style don't drift. **Up to 14 reference images** supported per call.

```python
# For each beat, generate 2-3 candidates conditioned on the anchor
def gen_keyframe_candidates(beat, anchor_b64, n=2):
    prompt = f"{beat.image_prompt}. Style: {board.global_style}. " \
             f"Use the reference image ONLY for character/style identity — keep the character identical."
    return [gen_image(prompt, refs=[anchor_b64]) for _ in range(n)]
```

Parallelize across beats with `concurrent.futures.ThreadPoolExecutor` (each `create` call is independent HTTP). This is our multi-agent fan-out.

**Multi-turn image edit** (alternative to regen — targeted fix from Critic):
```python
edit = client.interactions.create(
    model="gemini-3.1-flash-lite-image",
    input="Make the tiger's stripes match the reference. Do not change anything else.",
    previous_interaction_id=prev_image_interaction.id,
    response_format={"type": "image", "aspect_ratio": "16:9", "image_size": "1K"},
)
```

---

## 4. CRITIC agent — image understanding + structured score (the "reward")

Send candidate image(s) + anchor to Gemini, get back a structured score. Best-of-N selection = honest inference-time verifier-guided selection.

```python
class Verdict(BaseModel):
    prompt_adherence: int = Field(description="1-5")
    style_consistency: int = Field(description="1-5 vs anchor")
    composition: int = Field(description="1-5")
    # NOTE: 'continuity' axis DROPPED — parallel fan-out means no guaranteed prior
    # selected frame to compare against at score time (see ps_final.md step 4).
    best_index: int = Field(description="Index of best candidate")
    fix_prompt: str = Field(description="Targeted edit if best still < threshold, else empty")

# Regen rule: if BOTH candidates score < 3 on ANY axis → one targeted regen, then
# pick best-of-existing. HARD STOP, no further loop. (Tune the 3/5 threshold live.)

def critique(candidates_b64, anchor_b64, beat):
    parts = [{"type": "text",
              "text": f"Anchor is first image. Score each candidate against beat: {beat.action}. "
                      f"Return best_index and a fix_prompt if the best still needs work."},
             {"type": "image", "data": anchor_b64, "mime_type": "image/png"}]
    for c in candidates_b64:
        parts.append({"type": "image", "data": c, "mime_type": "image/png"})
    it = client.interactions.create(
        model="gemini-3.5-flash",
        input=parts,
        response_format={"type": "text", "mime_type": "application/json",
                         "schema": Verdict.model_json_schema()},
    )
    return Verdict.model_validate_json(it.output_text)
```

---

## 5. OMNI FLASH synthesis — keyframes → video

**Model ID:** `gemini-omni-flash-preview`

**Key facts:**
- Tasks: `text_to_video`, `image_to_video`, `reference_to_video`, `edit` (set via `generation_config={"video_config": {"task": ...}}`).
- Aspect ratio via `response_format={"type": "video", "aspect_ratio": "16:9"|"9:16"}`.
- Temporal prompting: prefix actions with time ranges like `"[0-3s] ..."`.
- ❌ **`image_to_video` accepts EXACTLY ONE image** (VERIFIED 2026-07-10). Passing a keyframe + reference images in one call is rejected: `BadRequestError: Image-to-video does not support more than 1 image.` The old "combined FIRST_FRAME + IMAGE_REF_N" idea is **UNSUPPORTED** — do not use it. Character consistency comes from the keyframe itself (already anchor-conditioned by NB2); describe any extra characters/props in the *text* prompt.
- ✅ **Omni generates its OWN audio** (VERIFIED — clips come back with a populated audio track: ambient/SFX, possibly music/voice). Our demo default relies on it. `"No dialogue or voiceover"` does NOT reliably silence it. TTS (§7) is a fallback we mix on top only if native audio is poor.
- **Unsupported:** system instructions, temperature, top_p, negative prompts, multi-video prompting, >1 image in image_to_video. Video references >3s not properly processed.
- For clips **>4MB** use `response_format={..., "delivery": "uri"}` then `client.files.download(file=uri)`.
- **NO duration parameter exists.** Clip length is not controllable; `[0-Xs]` timecodes only choreograph *content within* the clip. Observed ~5–10s. ✅ confirmed.
- **`store=True` for anything you'll re-direct** (see §0). Observed latency ~36s (image_to_video), ~48s (text_to_video).

**✅ Image-to-video — VERIFIED WORKING, our ONLY synthesis path:**
```python
def keyframe_to_video(keyframe_b64, motion_text, ar="16:9"):
    it = client.interactions.create(
        model="gemini-omni-flash-preview",
        input=[
            {"type": "image", "data": keyframe_b64, "mime_type": "image/png"},  # exactly ONE image
            {"type": "text", "text": motion_text},   # e.g. "[0-5s] the lion wakes. Single continuous shot, no scene cuts."
        ],
        generation_config={"video_config": {"task": "image_to_video"}},
        store=True,                                  # needed for re-direction
        response_format={"type": "video", "aspect_ratio": ar},
    )
    return it   # keep the whole interaction — need .id for re-direction; video at it.output_video.data (base64 str)
```

---

## 6. CONVERSATIONAL RE-DIRECTION — the Idea-4 money shot

Stateful edit of a previously generated video via `previous_interaction_id`. Re-runs only that segment.

```python
res1 = client.interactions.create(model="gemini-omni-flash-preview",
                                   input="A woman playing violin outdoors.")
res2 = client.interactions.create(
    model="gemini-omni-flash-preview",
    previous_interaction_id=res1.id,
    input="Make it night time. Keep everything else the same.",
)
open("shot2_v2.mp4","wb").write(base64.b64decode(res2.output_video.data))
```
Editing tips from docs: simple/precise edit prompts; add **"Keep everything else the same."**

---

## 7. NARRATION — Gemini TTS (strong Indian-language support)

**Model IDs:** `gemini-3.1-flash-tts-preview` (preferred), `gemini-2.5-flash-preview-tts`, `gemini-2.5-pro-preview-tts`.

**Indian languages supported:** Hindi (hi), Gujarati (gu), Kannada (kn), Marathi (mr), Odia (or), Punjabi (pa), Tamil (ta), Telugu (te). **Language auto-detected from input text** — no explicit lang param needed. 30 voices (Kore, Puck, Charon, Fenrir, Leda, …).

> ⚠️ **NOTE:** TTS is a FALLBACK for us, not the default. Omni Flash generates its own audio (see §5), and for the demo we lean on that. Use TTS only if Omni's native audio is poor, mixing it over or replacing the clip's track.

✅ **VERIFIED 2026-07-10:** TTS uses **`client.models.generate_content`**, NOT `interactions.create` (the interactions form is rejected). Config is a `GenerateContentConfig` with `response_modalities=["AUDIO"]` + a typed `SpeechConfig`. Audio PCM bytes (24kHz mono 16-bit) are at **`response.candidates[0].content.parts[0].inline_data.data`**.
```python
import wave, contextlib
from google.genai import types

@contextlib.contextmanager
def wave_file(fn, ch=1, rate=24000, sw=2):
    with wave.open(fn, "wb") as wf:
        wf.setnchannels(ch); wf.setsampwidth(sw); wf.setframerate(rate); yield wf

response = client.models.generate_content(     # NOT interactions.create
    model="gemini-3.1-flash-tts-preview",
    contents=beat["narration"],                # language auto-detected from text (Hindi/Tamil/etc.)
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore"))),
    ),
)

def extract_pcm(response):
    for cand in response.candidates:
        for part in cand.content.parts:
            if getattr(part, "inline_data", None):
                return part.inline_data.data
    return None

with wave_file("beat1.wav") as wf:
    wf.writeframes(extract_pcm(response))
```
Multi-speaker (≤2): use `types.MultiSpeakerVoiceConfig([types.SpeakerVoiceConfig(speaker="Joe", voice_config=...), ...])`; **speaker names must match names in the prompt text.**

---

## 8. STITCHING — assemble final short

**moviepy 2.x** (installed: 2.2.1). API differs from 1.x: `from moviepy import ...`
(no `.editor`), and `.set_audio`/`.set_duration` → **`.with_audio`/`.with_duration`**.

**DEFAULT (Omni native audio):** Omni clips already carry their own audio, so just concatenate — no per-beat narration needed.
```python
from moviepy import VideoFileClip, concatenate_videoclips

clips = [VideoFileClip(mp4) for mp4 in beat_mp4s]   # each keeps its native audio
final = concatenate_videoclips(clips)
final.write_videofile("chitrakatha.mp4", fps=24)
```

**FALLBACK (TTS narration):** only if Omni audio is poor. Never truncate narration, never time-stretch video — freeze-pad video and silence-pad audio to `max(video, audio)`. See `video/stitch.py::reconcile` for the full helper (handles moviepy 2.x AudioArrayClip silence padding + optional mix-over-native via `CompositeAudioClip`).
`pip install moviepy` (needs ffmpeg).

---

## 9. Reference pipeline (cookbook `Animated_Story_Video_Generation`)

Their 5-stage flow closely mirrors ours — good template to crib structure from:
1. Story → scenes (structured JSON, character consistency enforced via schema)
2. Per-scene image (they used Imagen; **we use NB2 Lite + anchor conditioning — our upgrade**)
3. Narration audio (Live API in theirs; **we use TTS Interactions call — simpler**)
4. Per-scene video composition (MoviePy)
5. Concatenate

**Our differentiators vs. this baseline:** (a) anchor-conditioned keyframes for true character consistency, (b) NB2→Omni *animation* instead of static Ken-Burns images, (c) verifier/critic best-of-N loop, (d) conversational segment re-direction.

---

## 10. Risk / gotcha checklist for demo day

- **Model IDs may differ** on provisioned accounts — first thing on arrival: confirm `gemini-omni-flash-preview`, `gemini-3.1-flash-lite-image`, `gemini-3.1-flash-tts-preview` all resolve. Have a `models.list()` check ready.
- **Omni latency** is the slow step → generate keyframes + critic **live** on stage (NB2 <4s each); **pre-render the final stitched video** as fallback.
- **Regional/EEA restrictions**: video editing + minors-in-images blocked in EEA/UK/CH — irrelevant in India but note if judges ask.
- **>4MB video** → must use `delivery: "uri"` + polling, not inline base64.
- **No temperature/top_p** anywhere in the new API — strip them from any copied snippet.
- Parallelize NB2 keyframe calls with a thread pool; keep the Omni calls sequential to avoid rate limits.
- **`store=True` on all Omni beats** — `store=False` (a common speed tip) silently kills the step-6 re-direction. Don't copy it onto editable clips.
- **Duration is uncontrollable** — observed ~5–10s clips. If mixing TTS, reconcile in MoviePy (never truncate narration; freeze-pad video, silence-pad audio).
- ❌ **image_to_video takes ONE image only** (verified). No keyframe+refs combo. Consistency lives in the keyframe; extra subjects go in the text prompt.
- ✅ **Omni makes its own audio** (verified) — demo default uses it; TTS is fallback only.
- ✅ **TTS = `models.generate_content`**, bytes at `candidates[0].content.parts[0].inline_data.data` (verified).
- **First 5 min:** `python -m common.client` — confirm all 4 model IDs resolve (all did on 2026-07-10 test account).
