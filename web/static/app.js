"use strict";

const CROW_STORY =
  "The Thirsty Crow (Panchatantra): on a hot day, a clever black crow searches a dry " +
  "Indian village for water, finds a pot with water too low to reach, and drops pebbles " +
  "in one by one until the water rises enough to drink.";

const STORY_CHIPS = [
  ["The Thirsty Crow", CROW_STORY],
  ["Lion & Mouse", "The Lion and the Mouse: a mighty lion spares a tiny mouse, who later frees the lion from a tangle of jungle vines."],
  ["Monkey & Crocodile", "The Monkey and the Crocodile: a clever monkey outwits a crocodile who wants his heart, escaping back to his berry tree."],
];

const REDIRECT_CHIPS = [
  ["Make it rainy", { mode: "edit", beat_id: 0, prompt: "Make it rain with a stormy sky. Keep everything else the same." }],
  ["Golden sunset", { mode: "edit", beat_id: 0, prompt: "Change the lighting to a warm golden sunset. Keep everything else the same." }],
  ["Swap crow → parrot", { mode: "swap", old: "crow", new: "green parrot" }],
];

const $ = (id) => document.getElementById(id);
const STAGES = [
  ["director", "Director"],
  ["anchors", "Anchors"],
  ["keyframes", "Keyframes"],
  ["critic", "Reward loop"],
  ["harmonize", "Coherence"],
];

let currentRun = "demo";       // pre-baked run for Act 2/3
const beatCards = {};          // beat_id -> card element

// ---- setup chips ----
function initChips() {
  const sc = $("story-chips");
  STORY_CHIPS.forEach(([label, text]) => {
    const b = document.createElement("span");
    b.className = "chip"; b.textContent = label;
    b.onclick = () => { $("story-input").value = text; };
    sc.appendChild(b);
  });
  $("story-input").value = CROW_STORY;

  const rc = $("redirect-chips");
  REDIRECT_CHIPS.forEach(([label, payload]) => {
    const b = document.createElement("span");
    b.className = "chip"; b.textContent = label;
    b.onclick = () => runRedirect(payload);
    rc.appendChild(b);
  });
}

// ---- stage tracker ----
function initTracker() {
  const t = $("stage-tracker"); t.hidden = false; t.innerHTML = "";
  STAGES.forEach(([key, label]) => {
    const p = document.createElement("div");
    p.className = "stage-pill"; p.id = "pill-" + key;
    p.innerHTML = `<span class="dot"></span>${label}`;
    t.appendChild(p);
  });
}
function setStage(key, status) {
  const p = $("pill-" + key);
  if (!p) return;
  // mark prior running as done
  document.querySelectorAll(".stage-pill.running").forEach((el) => {
    if (el !== p) el.classList.replace("running", "done");
  });
  p.classList.remove("running", "done");
  p.classList.add(status);
}

// ---- beat cards ----
function ensureCard(beat_id) {
  if (beatCards[beat_id]) return beatCards[beat_id];
  const c = document.createElement("div");
  c.className = "beat-card";
  c.innerHTML = `<img alt="beat ${beat_id}" /><div class="cap"><b>Beat ${beat_id}</b> <span class="act-txt"></span></div><div class="reward-chips"></div>`;
  $("storyboard").appendChild(c);
  beatCards[beat_id] = c;
  return c;
}

// ---- Act 1: direct (SSE) ----
function direct() {
  const story = $("story-input").value.trim();
  if (!story) return;
  $("direct-btn").disabled = true;
  $("storyboard").innerHTML = "";
  Object.keys(beatCards).forEach((k) => delete beatCards[k]);
  initTracker();

  // POST then read the SSE body via fetch stream (EventSource is GET-only).
  fetch("/api/direct", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ story }),
  }).then((resp) => {
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    function pump() {
      return reader.read().then(({ done, value }) => {
        if (done) return finishDirect();
        buf += dec.decode(value, { stream: true });
        const chunks = buf.split("\n\n"); buf = chunks.pop();
        for (const ch of chunks) handleSSE(ch);
        return pump();
      });
    }
    return pump();
  }).catch((e) => {
    $("direct-btn").disabled = false;
    alert("pipeline error: " + e);
  });
}

function handleSSE(chunk) {
  const ev = /event: (.+)/.exec(chunk);
  const dm = /data: (.+)/s.exec(chunk);
  if (!ev || !dm) return;
  const type = ev[1].trim();
  let data; try { data = JSON.parse(dm[1]); } catch { return; }

  if (type === "stage") {
    setStage(data.stage, data.status === "running" ? "running" : "done");
  } else if (type === "director") {
    data.beats.forEach((b) => {
      const c = ensureCard(b.beat_id);
      c.querySelector(".act-txt").textContent = b.action || "";
    });
  } else if (type === "anchor") {
    // show anchors as a strip above the storyboard (once)
    let strip = $("anchor-strip");
    if (!strip) {
      strip = document.createElement("div");
      strip.id = "anchor-strip"; strip.className = "anchor-strip";
      $("storyboard").before(strip);
    }
    const img = document.createElement("img");
    img.src = data.image; img.title = data.name; strip.appendChild(img);
  } else if (type === "beat_winner") {
    const c = ensureCard(data.beat_id);
    c.querySelector("img").src = data.image;
    c.querySelector(".act-txt").textContent = data.action || "";
    renderTrajectory(c, data.trajectory);
  } else if (type === "beat_final") {
    const c = ensureCard(data.beat_id);
    c.querySelector("img").src = data.image;  // harmonized version
  } else if (type === "done") {
    setStage("harmonize", "done");
  } else if (type === "error") {
    $("redirect-status").textContent = "";
    alert("pipeline: " + data.message);
  }
}

function renderTrajectory(card, traj) {
  const box = card.querySelector(".reward-chips");
  box.innerHTML = "";
  (traj || []).forEach((it) => {
    const chip = document.createElement("span");
    chip.className = "rchip " + (it.earned ? "earned" : "fixed");
    chip.textContent = `#${it.iter} r=${it.reward}/5${it.earned ? " ✓" : ""}`;
    chip.title = JSON.stringify(it.scores);
    box.appendChild(chip);
  });
}

function finishDirect() {
  setStage("harmonize", "done");
  $("direct-btn").disabled = false;
  $("act2").hidden = false;
  $("act3").hidden = false;
  $("act2").scrollIntoView({ behavior: "smooth" });
  // Act 2 now ANIMATES the just-narrated story live (matches what was typed),
  // instead of loading the pre-baked crow. ~40s/beat with progress.
  animateLive("live_run");
}

// ---- Act 2: live video synthesis for the narrated story ----
function animateLive(run) {
  currentRun = run;
  const note = document.querySelector("#act2 .act-note");
  note.innerHTML = 'Animating your story through Omni Flash — all shots at once, in parallel. <em>(live, ~60s for the whole film)</em>';
  let bar = $("animate-progress");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "animate-progress"; bar.className = "stage-tracker";
    $("act2").querySelector(".film-frame").before(bar);
  }
  bar.innerHTML = ""; bar.hidden = false;

  fetch("/api/animate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run }),
  }).then((resp) => {
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    function pump() {
      return reader.read().then(({ done, value }) => {
        if (done) return;
        buf += dec.decode(value, { stream: true });
        const chunks = buf.split("\n\n"); buf = chunks.pop();
        for (const ch of chunks) handleAnimateSSE(ch, bar);
        return pump();
      });
    }
    return pump();
  }).catch((e) => { note.innerHTML = "⚠ animation error: " + e; });
}

function handleAnimateSSE(chunk, bar) {
  const ev = /event: (.+)/.exec(chunk);
  const dm = /data: (.+)/s.exec(chunk);
  if (!ev || !dm) return;
  const type = ev[1].trim();
  let d; try { d = JSON.parse(dm[1]); } catch { return; }

  if (type === "animate_start") {
    for (let i = 0; i < d.beats; i++) {
      const p = document.createElement("div");
      p.className = "stage-pill"; p.id = "abeat-" + i;
      p.innerHTML = `<span class="dot"></span>Shot ${i + 1}`;
      bar.appendChild(p);
    }
  } else if (type === "animate_beat") {
    const p = $("abeat-" + (d.index - 1));
    if (p) {
      p.classList.remove("running", "done");
      if (d.status === "running") p.classList.add("running");
      else if (d.status === "done") p.classList.add("done");
      else if (d.status === "blocked") { p.classList.add("done"); p.style.background = "#7a2e1e"; p.style.color = "#fff"; }
    }
  } else if (type === "stage" && d.stage === "stitch") {
    document.querySelector("#act2 .act-note").innerHTML = "Stitching the film… <em>(almost there)</em>";
  } else if (type === "animate_done") {
    bar.hidden = true;
    document.querySelector("#act2 .act-note").innerHTML =
      "Your story, animated end-to-end — storyboard-conditioned, generated live.";
    $("film").src = d.video; $("film").load();
    $("act3").scrollIntoView({ behavior: "smooth" });
  } else if (type === "error") {
    document.querySelector("#act2 .act-note").innerHTML = "⚠ " + d.message;
  }
}

// ---- Act 3: redirect ----
function runRedirect(payload) {
  const st = $("redirect-status");
  st.textContent = "Re-shooting with Omni Flash… (~40s, generating live)";
  $("redirect-btn").disabled = true;

  // capture "before" from current film
  const beforeSrc = $("film").src;

  fetch("/api/redirect", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run: currentRun, ...payload }),
  }).then((r) => r.json()).then((d) => {
    $("redirect-btn").disabled = false;
    if (d.error) { st.textContent = "⚠ " + d.error; return; }
    st.textContent = `Re-shot beat(s) ${d.changed_beats.join(", ")} live.`;
    const firstBeat = d.changed_beats[0];
    const afterClip = d.beat_clips[firstBeat];
    if (afterClip) {
      $("beforeafter").hidden = false;
      $("ba-before").src = beforeSrc;
      $("ba-after").src = afterClip;
    }
    if (d.short) {
      $("restitch-frame").hidden = false;
      $("film-v2").src = d.short;
      $("film-v2").load();
    }
  }).catch((e) => {
    $("redirect-btn").disabled = false;
    st.textContent = "⚠ " + e;
  });
}

// ---- wire up ----
initChips();
$("direct-btn").onclick = direct;
$("redirect-btn").onclick = () => {
  const txt = $("redirect-input").value.trim();
  if (!txt) return;
  // naive parse: "swap X for Y" -> swap; else edit beat 0
  const m = /swap (?:the )?(\w+).* (?:for|with|to) (?:a |an )?([\w ]+)/i.exec(txt);
  if (m) runRedirect({ mode: "swap", old: m[1], new: m[2].trim() });
  else runRedirect({ mode: "edit", beat_id: 0, prompt: txt + " Keep everything else the same." });
};
