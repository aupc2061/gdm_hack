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

from common.io import save_selected, load_selected
from common.schema import SelectedFrame
from story.director import direct_story
from story.anchors import generate_anchors
from story.keyframes import fan_out
from story.critic import reward_loop, harmonize
from story.run_story import _relevant_anchor_items
from video.redirect import RedirectSession
from video.synth import synth_beat, VideoBlocked
from video.stitch import build_native, build_final
from video.narrate import narrate

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

# Pre-baked demo run the frontend points at (Act 2 + Act 3 base).
DEMO_RUN_DIR = os.environ.get("CK_RUN_DIR", os.path.join(OUT, "crow_video"))
DEMO_STORY_DIR = os.environ.get("CK_STORY_DIR", os.path.join(OUT, "crow_story"))

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


def _story_pipeline_events(story: str, out_dir: str, q: "queue.Queue"):
    """Runs the live story pipeline in a worker thread, pushing SSE dicts to q.
    Sentinel None signals completion."""
    try:
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
        q.put(("animate_start", {"beats": n}))
        beat_clips = []
        for i, fr in enumerate(sorted(frames, key=lambda f: f.beat_id)):
            q.put(("animate_beat", {"beat_id": fr.beat_id, "index": i + 1, "total": n,
                                    "status": "running",
                                    "label": f"Animating beat {i + 1}/{n} through Omni Flash…"}))
            try:
                bc = synth_beat(fr, run_dir)
                # Narration: TTS the beat's line, mixed OVER Omni's ducked ambient bed.
                try:
                    wav = os.path.join(run_dir, f"beat{fr.beat_id}.wav")
                    narrate(fr.narration, wav)
                    bc.wav_path = wav
                except Exception as ne:
                    print(f"  narration failed beat {fr.beat_id}: {ne}", flush=True)
                beat_clips.append(bc)
                url = "/media/" + os.path.relpath(bc.mp4_path, OUT).replace(os.sep, "/")
                q.put(("animate_beat", {"beat_id": fr.beat_id, "index": i + 1, "total": n,
                                        "status": "done", "clip": url}))
            except VideoBlocked as e:
                q.put(("animate_beat", {"beat_id": fr.beat_id, "index": i + 1, "total": n,
                                        "status": "blocked", "message": str(e)[:120]}))
        if not beat_clips:
            q.put(("error", {"message": "all beats blocked by guardrails"}))
            return
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


def _redirect_blocking(r: RedirectReq) -> dict:
    run_dir = DEMO_RUN_DIR if r.run == "demo" else os.path.join(OUT, r.run)
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
