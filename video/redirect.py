"""Conversational re-direction — the Idea-4 money shot.

Owner: Person 2. Multi-turn stateful editing of generated Omni clips via
previous_interaction_id. Each edit CHAINS on the beat's latest version, so you
can hold a real conversation ("make it night" -> "now add rain" -> "zoom in").
After every edit the full 3-shot short is re-stitched with that beat swapped in,
so the audience sees the change both in isolation and in context.

VERIFIED 2026-07-10 (out/probe): previous_interaction_id editing works; the new
edit returns its OWN interaction id, which is itself editable (chainable).
Requires the prior call used store=True (synth.py does). Free-tier interactions
expire in ~1 day, so re-direct in the same session you generated.

Two ways to drive it:
  - Interactive REPL:   python -m video.redirect --run out/stage3
  - Scripted fallback:  python -m video.redirect --run out/stage3 --script
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from typing import List, Tuple

from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from common.client import get_client, MODEL_VIDEO
from common.schema import BeatClip
from video.stitch import build_native
from video.synth import extract_thoughts, _THINK_CONFIG

# Pin the art style on every edit/swap. Without this, Omni re-renders the changed
# element in a drifted style (observed: cute googly-eye / 3D-Pixar look creeping
# back on a crow->parrot swap). Keeps re-directions in the locked ACK comic look.
_STYLE_LOCK = ("Keep the exact same flat 2D Amar Chitra Katha comic art style — "
               "bold black ink outlines, flat colors — NOT 3D, NOT Pixar, NOT "
               "photorealistic, no cartoon googly eyes.")

# Scripted fallback: a pre-tested edit sequence for the demo. Each entry chains
# on the previous edit of the SAME beat (multi-turn), across beats too.
DEMO_SCRIPT: List[Tuple[int, str]] = [
    (0, "Make it night time with soft moonlight. Keep everything else the same."),
    (0, "Add gentle fireflies drifting in the air. Keep everything else the same."),
    (1, "Make it rain lightly. Keep everything else the same."),
]


def _extract_video_bytes(interaction) -> bytes:
    data = interaction.output_video.data
    return base64.b64decode(data) if isinstance(data, str) else data


class RedirectSession:
    """Holds per-beat editing state for one generated run.

    For each beat we track its CURRENT interaction id (starts at the original,
    advances with every edit) and its CURRENT clip path. Re-stitching always
    uses whatever the current clip of each beat is.
    """

    def __init__(self, run_dir: str):
        self.run_dir = run_dir
        ids_path = os.path.join(run_dir, "interactions.json")
        if not os.path.exists(ids_path):
            raise FileNotFoundError(f"{ids_path} not found — run video.run_video first")
        with open(ids_path) as f:
            original_ids = json.load(f)

        # beat_id -> current state. Original clip is beat<N>.mp4 (from synth).
        self.beats = {}
        for bid_str, iid in original_ids.items():
            bid = int(bid_str)
            self.beats[bid] = {
                "cur_id": iid,
                "orig_id": iid,
                "cur_clip": os.path.join(run_dir, f"beat{bid}.mp4"),
                "orig_clip": os.path.join(run_dir, f"beat{bid}.mp4"),
                "edits": 0,
            }
        self.stitch_version = 0
        self.history: List[dict] = []
        self._client = get_client()

    @property
    def beat_ids(self) -> List[int]:
        return sorted(self.beats)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(3),
           retry=retry_if_exception_type(Exception), reraise=True)
    def _omni_edit(self, prev_id: str, prompt: str, think: bool = False):
        kwargs = {"model": MODEL_VIDEO, "previous_interaction_id": prev_id, "input": prompt}
        if think:
            kwargs["generation_config"] = dict(_THINK_CONFIG)
        return self._client.interactions.create(**kwargs)

    def edit(self, beat_id: int, prompt: str, restitch: bool = True,
             think: bool = False) -> str:
        """Apply one conversational edit to a beat, chaining on its latest version.

        Returns the path to the new edited clip. Re-stitches the full short by
        default so the edit is visible in context. think=True surfaces Omni's
        physics/lighting reasoning (slower ~1.8x) and prints + saves it — a
        strong demo moment showing the model reason about the edit.
        """
        if beat_id not in self.beats:
            raise KeyError(f"no such beat {beat_id}; have {self.beat_ids}")
        st = self.beats[beat_id]

        # Pin the art style so edits don't drift into 3D/googly-eye (unless the
        # caller already embedded a style lock, e.g. swap_element / consistency fix).
        if "art style" not in prompt.lower():
            prompt = f"{prompt} {_STYLE_LOCK}"

        print(f"  [beat {beat_id}] edit #{st['edits'] + 1} (chaining on {st['cur_id'][:24]}...)")
        it = self._omni_edit(st["cur_id"], prompt, think=think)

        st["edits"] += 1
        new_clip = os.path.join(self.run_dir, f"beat{beat_id}_v{st['edits']}.mp4")
        with open(new_clip, "wb") as f:
            f.write(_extract_video_bytes(it))

        thought = extract_thoughts(it) if think else ""
        if thought:
            with open(new_clip.replace(".mp4", ".thought.txt"), "w") as f:
                f.write(thought)
            print(f"    reasoning: {thought[:200]}{'...' if len(thought) > 200 else ''}")

        # advance the beat's current pointers so the NEXT edit chains on THIS one
        st["cur_id"] = it.id
        st["cur_clip"] = new_clip
        self.history.append({"beat": beat_id, "prompt": prompt,
                             "new_id": it.id, "clip": new_clip, "thought": thought})
        print(f"    -> {new_clip}  (new interaction {it.id[:24]}...)")

        if restitch:
            short = self.restitch()
            print(f"    -> re-stitched short: {short}")
        return new_clip

    def restitch(self) -> str:
        """Concatenate the CURRENT clip of every beat into a fresh short."""
        self.stitch_version += 1
        clips = [BeatClip(beat_id=b, mp4_path=self.beats[b]["cur_clip"])
                 for b in self.beat_ids]
        out = os.path.join(self.run_dir, f"chitrakatha_v{self.stitch_version}.mp4")
        return build_native(clips, out)

    def swap_element(self, old: str, new: str, beats: List[int] | None = None,
                     think: bool = False) -> List[str]:
        """Timeline-wide conversational element swap: replace `old` with `new`
        across every affected beat, keeping everything else consistent, then
        re-stitch ONCE. This is the bar's "element swapping ... consistent
        multi-shot timeline" in one conversational operation.

        beats=None → apply to all beats (each edit chains on that beat's latest).
        Returns the list of new clip paths.
        """
        targets = beats if beats is not None else self.beat_ids
        prompt = (f"Replace the {old} with a {new}. Keep the {new} in the same pose, "
                  f"position, and action the {old} had. "
                  f"{_STYLE_LOCK} "
                  f"Keep everything else in the scene exactly the same.")
        print(f"SWAP: {old} -> {new} across beats {targets}")
        clips = []
        for b in targets:
            # restitch only after the last beat, so we stitch once
            clips.append(self.edit(b, prompt, restitch=False, think=think))
        short = self.restitch()
        print(f"  -> re-stitched short with {new}: {short}")
        return clips

    def reset(self, beat_id: int | None = None) -> None:
        """Revert a beat (or all beats) to its originally-generated clip/id."""
        targets = [beat_id] if beat_id is not None else self.beat_ids
        for b in targets:
            st = self.beats[b]
            st["cur_id"], st["cur_clip"], st["edits"] = st["orig_id"], st["orig_clip"], 0
        print(f"  reset {'beat ' + str(beat_id) if beat_id is not None else 'all beats'}")

    def show(self) -> None:
        print(f"  run: {self.run_dir}")
        for b in self.beat_ids:
            st = self.beats[b]
            tag = f"{st['edits']} edit(s)" if st["edits"] else "original"
            print(f"    beat {b}: {os.path.basename(st['cur_clip'])}  [{tag}]")


# ---------------------------------------------------------------------------
# Scripted fallback
# ---------------------------------------------------------------------------

def run_script(session: RedirectSession, script: List[Tuple[int, str]] = DEMO_SCRIPT) -> None:
    print(f"Running scripted re-direction ({len(script)} edits)...")
    for beat_id, prompt in script:
        session.edit(beat_id, prompt)
    print("\nScripted sequence complete.")
    session.show()


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------

_HELP = """commands:
  edit <beat> <instruction>   apply an edit to a beat (chains on its latest version)
  editx <beat> <instruction>  same, but show Omni's physics/lighting REASONING (slower)
  swap <old> <new>            replace <old> with <new> across ALL beats, re-stitch once
  show                        list current state of each beat
  reset [beat]                revert a beat (or all) to the original
  script                      run the pre-baked DEMO_SCRIPT
  help                        this message
  quit / q                    exit
"""


def repl(session: RedirectSession) -> None:
    print("ChitraKatha re-direction session. Type 'help' for commands.\n")
    session.show()
    while True:
        try:
            line = input("\nredirect> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if not line:
            continue
        cmd, *rest = line.split(maxsplit=1)
        arg = rest[0] if rest else ""
        try:
            if cmd in ("quit", "q", "exit"):
                break
            elif cmd == "help":
                print(_HELP)
            elif cmd == "show":
                session.show()
            elif cmd == "script":
                run_script(session)
            elif cmd == "reset":
                session.reset(int(arg) if arg.strip() else None)
            elif cmd in ("edit", "editx"):
                b, *p = arg.split(maxsplit=1)
                if not p:
                    print(f"  usage: {cmd} <beat> <instruction>")
                    continue
                session.edit(int(b), p[0], think=(cmd == "editx"))
            elif cmd == "swap":
                parts = arg.split()
                if len(parts) != 2:
                    print("  usage: swap <old> <new>   (e.g. swap mouse squirrel)")
                    continue
                session.swap_element(parts[0], parts[1])
            else:
                print(f"  unknown command '{cmd}' — type 'help'")
        except Exception as e:
            # Never crash the live demo on a bad edit / expired interaction.
            print(f"  !! {type(e).__name__}: {str(e)[:160]}")
            print("     (interaction may have expired, or Omni rejected the edit — try again)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Multi-turn conversational re-direction.")
    ap.add_argument("--run", default="out/stage3",
                    help="run dir containing interactions.json + beat<N>.mp4")
    ap.add_argument("--script", action="store_true",
                    help="run the pre-baked DEMO_SCRIPT instead of the interactive REPL")
    # single-shot convenience (backward compatible)
    ap.add_argument("--beat", type=int, help="one-shot: edit this beat then exit")
    ap.add_argument("--prompt", help="one-shot: the edit instruction")
    ap.add_argument("--swap", nargs=2, metavar=("OLD", "NEW"),
                    help="one-shot: swap OLD element for NEW across all beats")
    ap.add_argument("--think", action="store_true",
                    help="surface Omni's physics/lighting reasoning (slower ~1.8x)")
    args = ap.parse_args()

    session = RedirectSession(args.run)
    if args.swap:
        session.swap_element(args.swap[0], args.swap[1], think=args.think)
    elif args.beat is not None and args.prompt:
        session.edit(args.beat, args.prompt, think=args.think)
    elif args.script:
        run_script(session)
    else:
        repl(session)
