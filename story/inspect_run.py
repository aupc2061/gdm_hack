"""Inspection runner: execute the full story pipeline and SAVE EVERYTHING.

Unlike run_story.py (which only keeps the Critic's winners), this saves every
intermediate artifact so you can SEE how the pipeline works end to end:

  storyboard.json      the Director's full storyboard
  storyboard.txt       human-readable beat-by-beat summary
  anchors/             one reference PNG per character
  beatN/candM.png      every keyframe candidate the fan-out produced
  beatN/verdict.json   the Critic's scores + which candidate it picked
  beatN/WINNER.png     the selected keyframe (copy, for quick glance)
  selected.json        the real deliverable to video/ (+ sidecar PNGs)
  index.html           open this in a browser to view the whole flow

    python -m story.inspect_run --story "The Lion and the Mouse" --out inspect/run1

This is a story/-owned debugging tool. It does NOT change the seam or the
production pipeline — it reuses the same stage functions.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
from typing import Dict, List

from common.io import save_selected
from common.schema import SelectedFrame, Storyboard, Beat, Verdict
from story.director import direct_story
from story.anchors import generate_anchors, gen_image
from story.keyframes import fan_out
from story.critic import critique, _below_threshold, THRESHOLD, harmonize

DEFAULT_STORY = (
    "The Lion and the Mouse (Panchatantra): a mighty lion spares a tiny mouse; "
    "later the mouse gnaws the ropes of a hunter's net and frees the lion."
)


def _write_png(b64: str, path: str) -> None:
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))


def _relevant_anchor_items(beat: Beat, anchors: Dict[str, str]):
    txt = f"{beat.subject} {beat.action}".lower()
    items = [(n, b) for n, b in anchors.items() if n.lower() in txt]
    return items or list(anchors.items())


def _select_with_verdict(beat, board, candidates_b64, anchor_b64s):
    """Like critic.select_best but returns (winner_b64, verdict, all_candidates,
    regen_happened) so the inspector can show the scores and any regen."""
    v = critique(candidates_b64, anchor_b64s, beat)
    regen = False
    if _below_threshold(v) and v.fix_prompt:
        prompt = (f"{beat.image_prompt}. {v.fix_prompt}. Style: {board.global_style}. "
                  f"Keep characters identical to the references.")
        candidates_b64 = candidates_b64 + [gen_image(prompt, refs=anchor_b64s)]
        v = critique(candidates_b64, anchor_b64s, beat)
        regen = True
    idx = max(0, min(v.best_index, len(candidates_b64) - 1))
    return candidates_b64[idx], v, candidates_b64, regen


def run(story: str, out_dir: str, n_beats=None):
    os.makedirs(out_dir, exist_ok=True)
    report = {"story": story, "beats": []}

    # ---- Stage 1: Director ------------------------------------------------
    print("[1/4] Director...")
    board = direct_story(story, n_beats=n_beats)
    print(f"  Director chose {len(board.beats)} beats; chars={[c.name for c in board.characters]}")
    with open(os.path.join(out_dir, "storyboard.json"), "w") as f:
        f.write(board.model_dump_json(indent=2))
    with open(os.path.join(out_dir, "storyboard.txt"), "w") as f:
        f.write(f"STORY: {story}\n\nSTYLE: {board.global_style}\n")
        f.write(f"CHARACTERS: {', '.join(c.name for c in board.characters)}\n\n")
        for b in board.beats:
            f.write(f"--- BEAT {b.beat_id} ({b.duration_s}s) ---\n")
            f.write(f"  subject:   {b.subject}\n  action:    {b.action}\n")
            f.write(f"  setting:   {b.setting}\n  camera:    {b.camera}\n")
            f.write(f"  motion:    {b.motion}\n  narration: {b.narration}\n\n")
    report["style"] = board.global_style

    # ---- Stage 2: Anchors -------------------------------------------------
    print("[2/4] Anchors...")
    anchors = generate_anchors(board)
    anc_dir = os.path.join(out_dir, "anchors")
    os.makedirs(anc_dir, exist_ok=True)
    report["anchors"] = []
    for name, b64 in anchors.items():
        p = os.path.join(anc_dir, f"{name}.png")
        _write_png(b64, p)
        report["anchors"].append({"name": name, "png": f"anchors/{name}.png"})

    # ---- Stage 3: Keyframe fan-out ---------------------------------------
    print("[3/4] Keyframe fan-out...")
    candidates = fan_out(board, anchors)

    # ---- Stage 4: Critic + selection -------------------------------------
    print("[4/4] Critic + selection...")
    frames: List[SelectedFrame] = []
    for beat in board.beats:
        bdir = os.path.join(out_dir, f"beat{beat.beat_id}")
        os.makedirs(bdir, exist_ok=True)
        cands = candidates[beat.beat_id]
        items = _relevant_anchor_items(beat, anchors)
        names = [n for n, _ in items]
        anchor_b64s = [b for _, b in items]

        cand_files = []
        for j, c in enumerate(cands):
            _write_png(c, os.path.join(bdir, f"cand{j}.png"))
            cand_files.append(f"beat{beat.beat_id}/cand{j}.png")

        beat_report = {
            "beat_id": beat.beat_id, "action": beat.action, "narration": beat.narration,
            "duration_s": beat.duration_s, "anchor_names": names,
            "candidates": cand_files, "verdict": None, "winner_index": None,
            "regen": False, "winner_png": None,
        }

        if not cands:
            print(f"  beat {beat.beat_id}: 0 candidates -> skipped")
            report["beats"].append(beat_report)
            continue

        winner, verdict, all_cands, regen = _select_with_verdict(
            beat, board, cands, anchor_b64s)
        # if a regen was added, persist the extra candidate too
        for j in range(len(cand_files), len(all_cands)):
            _write_png(all_cands[j], os.path.join(bdir, f"cand{j}_regen.png"))
            cand_files.append(f"beat{beat.beat_id}/cand{j}_regen.png")
        with open(os.path.join(bdir, "verdict.json"), "w") as f:
            f.write(verdict.model_dump_json(indent=2))
        _write_png(winner, os.path.join(bdir, "WINNER.png"))

        beat_report.update({
            "candidates": cand_files,
            "verdict": verdict.model_dump(),
            "winner_index": verdict.best_index,
            "regen": regen,
            "winner_png": f"beat{beat.beat_id}/WINNER.png",
        })
        report["beats"].append(beat_report)

        frames.append(SelectedFrame(
            beat_id=beat.beat_id,
            selected_keyframe_b64=winner,
            anchor_b64s=anchor_b64s,
            anchor_names=names,
            motion_text=f"{beat.action}. {beat.camera}. {beat.motion}",
            duration_s=beat.duration_s,
            narration=beat.narration,
        ))

    # ---- The real deliverable (same as run_story) ------------------------
    deliverable = save_selected(frames, out_dir)
    report["deliverable"] = os.path.basename(deliverable)

    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    _write_html(report, os.path.join(out_dir, "index.html"))

    print(f"\nDONE -> {out_dir}")
    print(f"  open {os.path.join(out_dir, 'index.html')} to view the full pipeline")
    print(f"  deliverable for video/: {deliverable} ({len(frames)} beats)")
    return out_dir


def _write_html(report: dict, path: str) -> None:
    e = html.escape
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><title>ChitraKatha pipeline</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;background:#12100e;color:#eee;margin:0;padding:24px}",
        "h1{color:#f5c542}h2{color:#f5c542;border-bottom:1px solid #443}h3{color:#e8a}",
        ".row{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start}",
        ".card{background:#1e1b17;border:1px solid #443;border-radius:8px;padding:8px}",
        ".card img{width:280px;height:auto;border-radius:4px;display:block}",
        ".win{border:3px solid #4caf50}.cap{font-size:12px;color:#bbb;margin-top:6px;max-width:280px}",
        ".score{display:inline-block;background:#333;border-radius:4px;padding:2px 8px;margin:2px;font-size:13px}",
        ".flow{color:#888;font-size:13px}.pill{background:#4caf50;color:#000;padding:2px 8px;border-radius:10px;font-size:11px}",
        "</style></head><body>",
        "<h1>ChitraKatha — full pipeline inspection</h1>",
        f"<p class='flow'>STORY → DIRECTOR → ANCHORS → KEYFRAME FAN-OUT → CRITIC → deliverable</p>",
        f"<div class='card'><b>Input story</b><div class='cap'>{e(report['story'])}</div>",
        f"<div class='cap'><b>Style:</b> {e(report.get('style',''))}</div></div>",
        "<h2>1 · Anchors (the consistency key — one per character)</h2><div class='row'>",
    ]
    for a in report.get("anchors", []):
        parts.append(f"<div class='card'><img src='{e(a['png'])}'><div class='cap'>{e(a['name'])}</div></div>")
    parts.append("</div>")

    parts.append("<h2>2 · Beats — candidates, Critic scores, winner</h2>")
    for b in report["beats"]:
        parts.append(f"<h3>Beat {b['beat_id']} &middot; {b['duration_s']}s"
                     + (" <span class='pill'>REGEN FIRED</span>" if b.get("regen") else "") + "</h3>")
        parts.append(f"<div class='cap'><b>action:</b> {e(b['action'])}<br><b>narration:</b> {e(b['narration'])}</div>")
        v = b.get("verdict")
        if v:
            parts.append(
                f"<div><span class='score'>prompt {v['prompt_adherence']}/5</span>"
                f"<span class='score'>style {v['style_consistency']}/5</span>"
                f"<span class='score'>composition {v['composition']}/5</span>"
                f"<span class='score'>threshold={THRESHOLD}</span></div>")
            if v.get("fix_prompt"):
                parts.append(f"<div class='cap'><b>fix_prompt:</b> {e(v['fix_prompt'])}</div>")
        parts.append("<div class='row'>")
        for j, c in enumerate(b["candidates"]):
            win = (j == b.get("winner_index"))
            cls = "card win" if win else "card"
            label = f"candidate {j}" + (" ✓ WINNER" if win else "")
            parts.append(f"<div class='{cls}'><img src='{e(c)}'><div class='cap'>{label}</div></div>")
        parts.append("</div>")

    parts.append(f"<h2>3 · Deliverable to video/</h2>"
                 f"<div class='card'><div class='cap'>Serialized to "
                 f"<b>{e(report.get('deliverable','selected.json'))}</b> — "
                 f"{len(report['beats'])} beats. This is what your teammate consumes.</div></div>")
    parts.append("</body></html>")
    with open(path, "w") as f:
        f.write("\n".join(parts))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", default=DEFAULT_STORY)
    ap.add_argument("--out", default="inspect/run1")
    ap.add_argument("--beats", type=int, default=None,
                    help="Force a beat count; omit to let the Director choose.")
    args = ap.parse_args()
    run(args.story, args.out, args.beats)
