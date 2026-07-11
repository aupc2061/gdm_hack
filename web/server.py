"""ChitraKatha demo backend (FastAPI).

Thin async wrapper over the existing pipeline — imports story/, video/, common/
functions and does NOT reimplement any pipeline logic. Serves a 3-act storybook
frontend:

  Act 1 (LIVE)      POST /api/direct  -> SSE stream of story-pipeline stages
  Act 2 (pre-baked) GET  /api/run/{run}     -> storyboard + video URLs
  Act 3 (LIVE edit) POST /api/redirect      -> RedirectSession edit / swap

Run:  uvicorn web.server:app --host 0.0.0.0 --port 8000
Env:  CK_RUN_DIR (default out/crow_video), CK_STORY_DIR (default out/crow_story)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import threading
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import (StreamingResponse, JSONResponse, FileResponse,
                               HTMLResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from common.io import save_selected, load_selected, png_to_b64
from common.schema import SelectedFrame
from story.director import direct_story
from story.anchors import generate_anchors
from story.keyframes import fan_out
from story.critic import reward_loop, harmonize
from story.run_story import _relevant_anchor_items
from video.redirect import RedirectSession
from video.synth import synth_beat, synth_all, VideoBlocked
from video.stitch import build_native, build_final
from video.narrate import narrate

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

# Pre-baked demo run the frontend points at (Act 2 + Act 3 base).
DEMO_RUN_DIR = os.environ.get("CK_RUN_DIR", os.path.join(OUT, "crow_video"))
DEMO_STORY_DIR = os.environ.get("CK_STORY_DIR", os.path.join(OUT, "crow_story"))
# CK_DEMO_CACHE=1 -> the crow story replays pre-baked artifacts instantly (Act 1
# storyboard, Act 2 film, Act 3 edit) for smooth recording. Other stories run live.
DEMO_CACHE = os.environ.get("CK_DEMO_CACHE", "").lower() in ("1", "true", "yes")

app = FastAPI(title="ChitraKatha")

# Serve generated media (read-only) and the static frontend.
if os.path.isdir(OUT):
    app.mount("/media", StaticFiles(directory=OUT), name="media")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


def _b64_data_uri(b64: str) -> str:
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Act 1 — LIVE story pipeline, streamed as Server-Sent Events.
# Re-runs the same stage functions as story.run_story.run(), emitting an event
# after each stage so the frontend can animate the "agents working".
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _is_crow_story(story: str) -> bool:
    return "crow" in (story or "").lower()


def _replay_cached_story(out_dir: str, q: "queue.Queue"):
    """Demo cache: replay the pre-baked crow storyboard/anchors/keyframes/reward
    trajectory as SSE — streamed with small delays so it reads as live — instead
    of the ~93s real pipeline. Copies selected.json + PNGs into out_dir so Act 2's
    cache finds them. Only used for the crow demo story; others run live."""
    import shutil, time as _t
    sd = DEMO_STORY_DIR
    manifest = json.load(open(os.path.join(sd, "selected.json")))
    trace = json.load(open(os.path.join(sd, "reward_trace.json"))) if os.path.exists(os.path.join(sd, "reward_trace.json")) else []
    trace_by_id = {t["beat_id"]: t for t in trace}

    q.put(("stage", {"stage": "director", "status": "running", "label": "Director agent reading your story..."}))
    _t.sleep(0.6)
    q.put(("director", {"beats": [{"beat_id": m["beat_id"], "action": trace_by_id.get(m["beat_id"], {}).get("action", ""),
                                   "setting": "", "narration": m.get("narration", "")} for m in manifest],
                        "characters": m0_names(manifest)}))
    q.put(("stage", {"stage": "anchors", "status": "running", "label": "Generating character anchors (the consistency key)..."}))
    # anchors: one strip, from the first beat's anchor pngs
    for i, ap in enumerate(manifest[0].get("anchor_pngs", [])):
        _t.sleep(0.3)
        q.put(("anchor", {"name": (manifest[0].get("anchor_names") or [f"ref{i}"])[i] if i < len(manifest[0].get("anchor_names", [])) else f"ref{i}",
                          "image": _b64_data_uri(png_to_b64(os.path.join(sd, ap)))}))
    q.put(("stage", {"stage": "keyframes", "status": "running", "label": "Keyframe agents fanning out per beat..."}))
    _t.sleep(0.4)
    q.put(("stage", {"stage": "critic", "status": "running", "label": "Verifier-guided reward loop — earning each keyframe..."}))
    for m in manifest:
        _t.sleep(0.7)
        q.put(("beat_winner", {"beat_id": m["beat_id"],
                               "action": trace_by_id.get(m["beat_id"], {}).get("action", ""),
                               "image": _b64_data_uri(png_to_b64(os.path.join(sd, m["keyframe_png"]))),
                               "trajectory": trace_by_id.get(m["beat_id"], {}).get("iterations", [])}))
    q.put(("stage", {"stage": "harmonize", "status": "running", "label": "Global coherence pass — matching the whole set..."}))
    _t.sleep(0.6)
    # copy the whole story dir into out_dir so Act 2 cache + video have the seam
    os.makedirs(out_dir, exist_ok=True)
    for fn in os.listdir(sd):
        shutil.copy(os.path.join(sd, fn), os.path.join(out_dir, fn))
    q.put(("done", {"beats": len(manifest), "run": os.path.basename(out_dir), "cached": True}))


def m0_names(manifest):
    return manifest[0].get("anchor_names", []) if manifest else []


def _story_pipeline_events(story: str, out_dir: str, q: "queue.Queue"):
    """Runs the live story pipeline in a worker thread, pushing SSE dicts to q.
    Sentinel None signals completion."""
    try:
        # DEMO CACHE: crow story -> replay pre-baked storyboard instantly (streamed
        # to look live). Any other story runs the real ~93s pipeline below.
        if DEMO_CACHE and _is_crow_story(story) and os.path.exists(os.path.join(DEMO_STORY_DIR, "selected.json")):
            print("  [demo-cache] crow story -> replaying pre-baked storyboard", flush=True)
            _replay_cached_story(out_dir, q)
            return

        q.put(("stage", {"stage": "director", "status": "running",
                         "label": "Director agent reading your story..."}))
        board = direct_story(story)
        q.put(("director", {"beats": [
            {"beat_id": b.beat_id, "action": b.action, "setting": b.setting,
             "narration": b.narration} for b in board.beats],
            "characters": [c.name for c in board.characters]}))

        q.put(("stage", {"stage": "anchors", "status": "running",
                         "label": "Generating character anchors (the consistency key)..."}))
        anchors = generate_anchors(board)
        for name, b64 in anchors.items():
            q.put(("anchor", {"name": name, "image": _b64_data_uri(b64)}))

        q.put(("stage", {"stage": "keyframes", "status": "running",
                         "label": "Keyframe agents fanning out per beat..."}))
        candidates = fan_out(board, anchors)

        q.put(("stage", {"stage": "critic", "status": "running",
                         "label": "Verifier-guided reward loop — earning each keyframe..."}))
        frames, picked_beats, picked_anchors = [], [], []
        for beat in board.beats:
            items = _relevant_anchor_items(beat, anchors)
            names = [n for n, _ in items]
            anchor_b64s = [b for _, b in items]
            cands = candidates.get(beat.beat_id, [])
            if not cands:
                q.put(("beat_skip", {"beat_id": beat.beat_id}))
                continue
            best, trajectory = reward_loop(beat, board, cands, anchor_b64s)
            q.put(("beat_winner", {
                "beat_id": beat.beat_id, "action": beat.action,
                "image": _b64_data_uri(best),
                "trajectory": trajectory,  # reward score progression (the wow)
            }))
            frames.append(SelectedFrame(
                beat_id=beat.beat_id, selected_keyframe_b64=best,
                anchor_b64s=anchor_b64s, anchor_names=names,
                motion_text=f"{beat.action}. {beat.camera}. {beat.motion}",
                duration_s=beat.duration_s, narration=beat.narration))
            picked_beats.append(beat)
            picked_anchors.append(anchor_b64s)

        q.put(("stage", {"stage": "harmonize", "status": "running",
                         "label": "Global coherence pass — matching the whole set..."}))
        if len(frames) >= 2:
            harmonized = harmonize(picked_beats, [f.selected_keyframe_b64 for f in frames],
                                   picked_anchors, max_fixes=2)
            for f, h in zip(frames, harmonized):
                f.selected_keyframe_b64 = h
                q.put(("beat_final", {"beat_id": f.beat_id, "image": _b64_data_uri(h)}))

        os.makedirs(out_dir, exist_ok=True)
        save_selected(frames, out_dir)
        q.put(("done", {"beats": len(frames), "run": os.path.basename(out_dir)}))
    except Exception as e:
        q.put(("error", {"message": f"{type(e).__name__}: {str(e)[:200]}"}))
    finally:
        q.put(None)


@app.post("/api/direct")
async def direct(req: Request):
    body = await req.json()
    story = (body or {}).get("story", "").strip()
    if not story:
        return JSONResponse({"error": "empty story"}, status_code=400)
    out_dir = os.path.join(OUT, "live_run")

    q: "queue.Queue" = queue.Queue()
    threading.Thread(target=_story_pipeline_events, args=(story, out_dir, q), daemon=True).start()

    async def stream():
        loop = asyncio.get_event_loop()
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                break
            event, data = item
            yield _sse(event, data)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Act 2 (live) — synthesize video for the JUST-NARRATED story, per-beat progress.
# Runs Omni synth on out/live_run/selected.json so the film matches what the
# user typed (not the pre-baked crow). ~40s/beat — streamed so the wait is visible.
# ---------------------------------------------------------------------------

def _is_crow_run(frames) -> bool:
    """Detect the guardrail-safe demo story (crow) so we can serve the pre-baked,
    AAC, already-consistency-checked film instantly for a clean recording — while
    ANY OTHER story still runs Omni live. Keyed on the story content, not a flag."""
    names = " ".join(getattr(f, "name", "") for f in frames).lower()
    text = " ".join(fr.narration + " " + fr.motion_text for fr in frames).lower()
    return "crow" in names or "crow" in text


def _serve_cached_crow(run_dir: str, frames, q: "queue.Queue"):
    """Copy pre-baked crow_video artifacts into the live run dir and emit the
    same SSE events as a real synth, but instantly. Keeps Act 2 snappy on camera."""
    import shutil
    n = len(frames)
    q.put(("animate_start", {"beats": n}))
    for fr in sorted(frames, key=lambda f: f.beat_id):
        src = os.path.join(DEMO_RUN_DIR, f"beat{fr.beat_id}.mp4")
        dst = os.path.join(run_dir, f"beat{fr.beat_id}.mp4")
        if os.path.exists(src):
            shutil.copy(src, dst)
        q.put(("animate_beat", {"beat_id": fr.beat_id, "index": fr.beat_id + 1,
                                "total": n, "status": "done",
                                "clip": "/media/" + os.path.relpath(dst, OUT).replace(os.sep, "/")}))
    for extra in ("chitrakatha.mp4", "interactions.json"):
        s = os.path.join(DEMO_RUN_DIR, extra)
        if os.path.exists(s):
            shutil.copy(s, os.path.join(run_dir, extra))
    final = os.path.join(run_dir, "chitrakatha.mp4")
    q.put(("animate_done", {"video": "/media/" + os.path.relpath(final, OUT).replace(os.sep, "/"),
                            "run": os.path.basename(run_dir), "cached": True}))


def _animate_events(run: str, q: "queue.Queue"):
    try:
        run_dir = os.path.join(OUT, run)
        sel = os.path.join(run_dir, "selected.json")
        if not os.path.exists(sel):
            q.put(("error", {"message": f"no selected.json in {run} — narrate a story first"}))
            return
        frames = load_selected(sel)
        by_id = {fr.beat_id: fr for fr in frames}
        n = len(frames)

        # DEMO CACHE: crow story -> serve pre-baked film instantly (story still ran
        # live). Any other story falls through to real Omni synth below.
        if _is_crow_run(frames) and os.path.exists(os.path.join(DEMO_RUN_DIR, "chitrakatha.mp4")):
            print("  [demo-cache] crow story -> serving pre-baked crow_video", flush=True)
            _serve_cached_crow(run_dir, frames, q)
            return

        q.put(("animate_start", {"beats": n}))
        for fr in sorted(frames, key=lambda f: f.beat_id):
            q.put(("animate_beat", {"beat_id": fr.beat_id, "index": fr.beat_id + 1,
                                    "total": n, "status": "running",
                                    "label": f"Animating all {n} shots through Omni Flash, simultaneously…"}))

        # All beats' Omni calls fire CONCURRENTLY (no rate limits) — ~one beat's
        # time instead of N. synth_all skips guardrail-blocked beats.
        beat_clips = synth_all(frames, run_dir, parallel=True)
        got = {bc.beat_id for bc in beat_clips}
        for fr in frames:
            done = fr.beat_id in got
            data = {"beat_id": fr.beat_id, "index": fr.beat_id + 1, "total": n,
                    "status": "done" if done else "blocked"}
            if done:
                bc = next(b for b in beat_clips if b.beat_id == fr.beat_id)
                data["clip"] = "/media/" + os.path.relpath(bc.mp4_path, OUT).replace(os.sep, "/")
            q.put(("animate_beat", data))

        if not beat_clips:
            q.put(("error", {"message": "all beats blocked by guardrails"}))
            return

        # Narration per surviving beat (TTS over ducked Omni bed).
        q.put(("stage", {"stage": "narrate", "status": "running", "label": "Voicing the narration…"}))
        for bc in beat_clips:
            try:
                wav = os.path.join(run_dir, f"beat{bc.beat_id}.wav")
                narrate(by_id[bc.beat_id].narration, wav)
                bc.wav_path = wav
            except Exception as ne:
                print(f"  narration failed beat {bc.beat_id}: {ne}", flush=True)

        q.put(("stage", {"stage": "stitch", "status": "running",
                         "label": "Stitching the film + narration…"}))
        # narrate=True + keep_native=True => TTS narration over ducked Omni bed.
        have_narration = all(bc.wav_path for bc in beat_clips)
        final = build_final(beat_clips, os.path.join(run_dir, "chitrakatha.mp4"),
                            narrate=have_narration, keep_native=True)
        ids = {str(bc.beat_id): bc.omni_interaction_id for bc in beat_clips}
        with open(os.path.join(run_dir, "interactions.json"), "w") as f:
            json.dump(ids, f, indent=2)
        q.put(("animate_done", {
            "video": "/media/" + os.path.relpath(final, OUT).replace(os.sep, "/"),
            "run": run,
        }))
    except Exception as e:
        q.put(("error", {"message": f"{type(e).__name__}: {str(e)[:200]}"}))
    finally:
        q.put(None)


@app.post("/api/animate")
async def animate(req: Request):
    body = await req.json()
    run = (body or {}).get("run", "live_run")
    q: "queue.Queue" = queue.Queue()
    threading.Thread(target=_animate_events, args=(run, q), daemon=True).start()

    async def stream():
        loop = asyncio.get_event_loop()
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                break
            event, data = item
            yield _sse(event, data)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Act 2 — pre-baked run: storyboard + stitched short.
# ---------------------------------------------------------------------------

def _run_media_url(run_dir: str, filename: str) -> Optional[str]:
    p = os.path.join(run_dir, filename)
    if os.path.exists(p):
        return "/media/" + os.path.relpath(p, OUT).replace(os.sep, "/")
    return None


@app.get("/api/run/{run}")
def get_run(run: str):
    """Return the pre-baked run's storyboard (from story dir) + stitched video URL."""
    story_dir = DEMO_STORY_DIR if run == "demo" else os.path.join(OUT, run)
    video_dir = DEMO_RUN_DIR if run == "demo" else os.path.join(OUT, run)
    sel = os.path.join(story_dir, "selected.json")
    if not os.path.exists(sel):
        return JSONResponse({"error": f"no selected.json in {story_dir}"}, status_code=404)
    with open(sel) as f:
        manifest = json.load(f)
    beats = [{
        "beat_id": m["beat_id"],
        "narration": m.get("narration", ""),
        "keyframe": _run_media_url(story_dir, m["keyframe_png"]),
    } for m in manifest]
    ids_path = os.path.join(video_dir, "interactions.json")
    ids = json.load(open(ids_path)) if os.path.exists(ids_path) else {}
    return {
        "beats": beats,
        "video": _run_media_url(video_dir, "chitrakatha.mp4"),
        "interaction_ids": ids,
        "video_dir": os.path.basename(video_dir),
    }


# ---------------------------------------------------------------------------
# Act 3 — LIVE conversational re-direction (edit or element swap).
# ---------------------------------------------------------------------------

class RedirectReq(BaseModel):
    run: str = "demo"
    mode: str = "edit"          # "edit" | "swap"
    beat_id: Optional[int] = None
    prompt: Optional[str] = None    # for edit
    old: Optional[str] = None       # for swap
    new: Optional[str] = None       # for swap


def _cached_redirect(run_dir: str, beat_id: int) -> Optional[dict]:
    """For recording: if a pre-baked edited clip exists (beat<N>_v1.mp4 +
    chitrakatha_v1.mp4, copied from crow_video), serve it INSTANTLY instead of a
    ~40s live Omni edit. Only used when CK_DEMO_CACHE=1. Returns None if no cache."""
    src_clip = os.path.join(DEMO_RUN_DIR, f"beat{beat_id}_v1.mp4")
    src_short = os.path.join(DEMO_RUN_DIR, "chitrakatha_v1.mp4")
    if not (os.path.exists(src_clip) and os.path.exists(src_short)):
        return None
    import shutil
    dst_clip = os.path.join(run_dir, f"beat{beat_id}_v1.mp4")
    dst_short = os.path.join(run_dir, "chitrakatha_v1.mp4")
    shutil.copy(src_clip, dst_clip)
    shutil.copy(src_short, dst_short)
    return {
        "changed_beats": [beat_id],
        "beat_clips": {beat_id: "/media/" + os.path.relpath(dst_clip, OUT).replace(os.sep, "/")},
        "short": "/media/" + os.path.relpath(dst_short, OUT).replace(os.sep, "/"),
        "cached": True,
    }


def _redirect_blocking(r: RedirectReq) -> dict:
    run_dir = DEMO_RUN_DIR if r.run == "demo" else os.path.join(OUT, r.run)
    # Demo cache: serve a pre-baked edit instantly (recording). Env-gated so live
    # editing still works normally when CK_DEMO_CACHE is off.
    if DEMO_CACHE:
        cached = _cached_redirect(run_dir, r.beat_id if r.beat_id is not None else 0)
        if cached:
            print("  [demo-cache] serving pre-baked redirect", flush=True)
            return cached
    session = RedirectSession(run_dir)
    if r.mode == "swap" and r.old and r.new:
        clips = session.swap_element(r.old, r.new)
        changed = [b for b in session.beat_ids if session.beats[b]["edits"] > 0]
    else:
        if r.beat_id is None or not r.prompt:
            raise ValueError("edit needs beat_id + prompt")
        session.edit(r.beat_id, r.prompt)
        changed = [r.beat_id]
    short = os.path.join(run_dir, f"chitrakatha_v{session.stitch_version}.mp4")
    return {
        "changed_beats": changed,
        "beat_clips": {b: "/media/" + os.path.relpath(session.beats[b]["cur_clip"], OUT).replace(os.sep, "/")
                       for b in changed},
        "short": "/media/" + os.path.relpath(short, OUT).replace(os.sep, "/") if os.path.exists(short) else None,
    }


@app.post("/api/redirect")
async def redirect(r: RedirectReq):
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _redirect_blocking, r)
        return result
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=500)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))
