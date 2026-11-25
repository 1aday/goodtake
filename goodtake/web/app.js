const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const clock = (value) => {
  const n = Math.max(0, Number(value) || 0);
  return `${Math.floor(n / 60)}:${String(Math.floor(n % 60)).padStart(2, "0")}`;
};
const state = {
  projects: [],
  project: null,
  clipId: null,
  draft: null,
  brand: null,
  status: null,
  dirty: false,
  inspector: "style",
  view: "library",
  playhead: 0,
  previewMode: "layout",
  lastJob: null,
};
let toastTimer,
  pollBusy = false,
  previewObserver;
function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = error ? "error" : "";
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (element.hidden = true), error ? 10000 : 4500);
}
async function request(path, options = {}) {
  const headers = {
    ...(options.method && options.method !== "GET"
      ? { "X-Goodtake": "1" }
      : {}),
    ...options.headers,
  };
  let body = options.body;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const response = await fetch(path, { ...options, headers, body });
  const data = await response
    .json()
    .catch(() => ({ detail: `Request failed (${response.status})` }));
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
async function action(fn) {
  try {
    return await fn();
  } catch (error) {
    toast(error.message || "This action did not finish. Try again.", true);
    return null;
  }
}
function tag(status) {
  const text =
    {
      draft: "Draft",
      checked: "Checks passed",
      ready: "Approved",
      needs_review: "Needs review",
    }[status] || status;
  return `<span class="tag ${status === "ready" || status === "checked" ? "good" : status === "needs_review" ? "coral" : ""}">${esc(text)}</span>`;
}
function setNavigation(view) {
  state.view = view;
  $("#library-nav").classList.toggle("active", view !== "settings");
  $("#settings-nav").classList.toggle("active", view === "settings");
  $("#project-count").textContent = state.projects.length;
}
function activeJob() {
  return state.project?.jobs?.find((j) =>
    ["queued", "running", "cancelling"].includes(j.status),
  );
}
function currentClip() {
  return state.project?.clips.find((c) => c.id === state.clipId);
}
function clipInput(clip) {
  return Object.fromEntries(
    ["title", "start", "end", "takeaway", "reason", "post", "style"].map(
      (key) => [key, structuredClone(clip[key])],
    ),
  );
}
function dirty() {
  state.dirty = true;
  state.previewMode = "layout";
  const save = $("#save-clip");
  if (save) save.disabled = false;
  const exportButton = $("#export-clip");
  if (exportButton) exportButton.textContent = "Save & export clip ↗";
  $$(".inspector-actions a, #approve-clip").forEach((element) => element.hidden = true);
  const note = $(".inspector-actions .render-hint");
  if (note) note.textContent = "Unsaved draft. Save and export to check this version.";
  const status = $(".moment-item.active .tag");
  if (status) { status.textContent = "Unsaved draft"; status.className = "tag"; }
}

async function library() {
  if (state.dirty) await saveClip(false);
  state.project = null;
  state.draft = null;
  state.dirty = false;
  setNavigation("library");
  location.hash = "";
  state.projects = await request("/api/projects");
  $("#project-count").textContent = state.projects.length;
  $("#breadcrumbs").innerHTML = "Your studio <span>/</span> Conversations";
  const first = !state.projects.length;
  $("#content").innerHTML =
    `<section class="library"><div class="section-top"><div><span class="eyebrow">A LITTLE LESS EDITING. A LOT MORE SHARING.</span>
    <h1>Your conversations.</h1><p>The moments worth keeping, all in one place.</p></div><span class="quiet-count">${state.projects.length} ${state.projects.length === 1 ? "conversation" : "conversations"}</span></div>
    ${
      first
        ? `<div class="welcome"><div class="welcome-copy"><span class="eyebrow">GOOD CONVERSATIONS DESERVE BETTER CLIPS</span>
    <h2>Give the idea<br>room to land.</h2><p>Find a complete thought. Make it look like you. Share something worth watching.</p>
    <div class="welcome-actions"><button class="button primary" id="welcome-import">Import a conversation ↗</button><button class="button text" id="sample-button">Try the sample →</button></div>
    <div class="welcome-note">Local first. No account needed. The final cut is yours.</div></div><div class="welcome-art"><img src="/static/sample.jpg" alt="Two microphones connected by a continuous strip of film"></div></div>
    <div class="empty-library"><div><strong>01 / Find the whole thought</strong><p>A clear opening, a real payoff, and a natural place to stop.</p></div><div><strong>02 / Make it yours</strong><p>Expressive captions and considered layouts, in your own colours.</p></div><div><strong>03 / Check the finished file</strong><p>Review picture, captions and speech before you call it ready.</p></div></div>`
        : `<div class="project-grid">${state.projects
            .map(
              (
                p,
              ) => `<button class="project-card" data-project="${p.id}"><span class="project-thumb">${
                p.clips.find((c) => c.cover_url)
                  ? `<img src="${p.clips.find((c) => c.cover_url).cover_url}" alt="">`
                  : `<video src="${p.source_url_local}#t=0.5" preload="metadata" muted playsinline></video>`
              }
      ${p.sample ? '<span class="sample-label">SYNTHETIC SAMPLE</span>' : ""}</span><span class="project-card-body"><h3>${esc(p.title)}</h3><span class="project-meta"><span>${clock(p.duration)} · ${p.clips.length} ${p.clips.length === 1 ? "moment" : "moments"}</span><span>Open conversation ↗</span></span></span></button>`,
            )
            .join("")}</div>
      <div class="button-row" style="margin-top:24px"><button class="button text" id="sample-button">Try the bundled sample →</button></div>`
    }</section>`;
  $("#welcome-import")?.addEventListener("click", showImport);
  $("#sample-button")?.addEventListener("click", () =>
    action(async () => {
      $("#sample-button").disabled = true;
      const project = await request("/api/sample", { method: "POST" });
      state.projects = await request("/api/projects");
      await openProject(project.id);
      toast("Synthetic sample loaded. No provider calls were made.");
    }),
  );
  $$("[data-project]").forEach((button) =>
    button.addEventListener("click", () =>
      action(() => openProject(button.dataset.project)),
    ),
  );
}

async function openProject(id, clipId = null) {
  if (state.dirty) await saveClip(false);
  state.project = await request(`/api/projects/${id}`);
  state.clipId = clipId || state.project.clips[0]?.id || null;
  state.brand = structuredClone(state.project.brand);
  state.draft = state.clipId ? clipInput(currentClip()) : null;
  state.dirty = false;
  state.playhead = state.draft?.start || 0;
  state.previewMode = currentClip()?.video_url ? "export" : "layout";
  state.lastJob =
    state.project.jobs[0]?.id + ":" + state.project.jobs[0]?.status;
  setNavigation("project");
  location.hash = `project=${id}${state.clipId ? "&clip=" + state.clipId : ""}`;
  renderProject();
}
function renderProject() {
  const p = state.project,
    clip = currentClip(),
    ready = p.clips.filter((c) => c.status === "ready").length;
  $("#breadcrumbs").innerHTML =
    `<button class="button text" id="back-library">Conversations</button><span>/</span>${esc(p.title)}`;
  $("#content").innerHTML =
    `<section class="project-header"><div class="project-header-top"><div><span class="eyebrow">THE CONVERSATION</span><h1>${esc(p.title)}</h1></div>
    <div class="project-actions"><button class="button" id="find-moments">✦ Find moments</button><a class="button ${ready ? "" : "disabled"}" id="download-kit" ${ready ? `href="/api/projects/${p.id}/kit"` : 'aria-disabled="true"'}>↓ Guest kit${ready ? " · " + ready : ""}</a></div></div>
    <div class="project-stats"><span>${esc(p.brand.show)}</span><span class="dot-separator">/</span><span>${clock(p.duration)} original</span><span class="dot-separator">/</span><span>${p.clips.length} ${p.clips.length === 1 ? "moment" : "moments"}</span>${p.sample ? '<span class="tag coral">Synthetic sample · prepared selection</span>' : ""}
    ${p.transcript ? `<span class="tag">${esc(p.transcript.method)}</span>` : ""}</div></section><div id="jobs"></div>
    ${
      clip
        ? `<section class="editor"><aside class="moments-rail"><div class="rail-heading"><h2>Selected moments</h2><span>${p.clips.length}</span></div>
      ${p.clips.map((c, i) => `<button class="moment-item ${c.id === state.clipId ? "active" : ""}" data-clip="${c.id}"><span class="moment-index"><span>0${i + 1}</span>${tag(c.status)}</span><span class="moment-title">${esc(c.title)}</span><span class="moment-time">${clock(c.start)} — ${clock(c.end)} <span style="float:right">${Math.round(c.end - c.start)}s</span></span></button>`).join("")}
      <button class="add-moment" id="add-moment">＋ Add a moment</button><p class="rail-note">One complete thought.<br>Original voice. Your final say.</p></aside>
      <div class="preview-pane"><div class="preview-top"><span class="label"><span class="local-dot"></span><span id="preview-label">LAYOUT PREVIEW</span></span><button class="button text small" id="toggle-preview">${clip.video_url ? "Change preview" : "Original speech"}</button></div>
      <div id="preview-holder" style="width:100%;display:flex;justify-content:center"></div><div class="preview-controls"><button class="play-button" id="play-selection" aria-label="Play selection">▶</button>
      <input id="playhead-range" aria-label="Source playhead" type="range" min="0" max="${p.duration}" step=".05" value="${state.playhead}" style="flex:1;min-width:30px;accent-color:#647f50">
      <span class="playhead" id="playhead-time">${clock(state.playhead)} / ${clock(p.duration)}</span></div>
      <p class="preview-footnote" id="preview-note">${clip.video_url ? "Watch the actual encoded export." : "Layout preview uses your original footage. Export checks run on the finished file."}</p></div>
      <aside class="inspector"><div class="inspector-head"><span class="eyebrow">THE HOOK</span><textarea id="clip-title" class="headline-input" rows="2" maxlength="65" aria-label="Clip headline">${esc(state.draft.title)}</textarea></div>
      <nav class="tabs" aria-label="Clip controls">${["style", "words", "checks"].map((tab) => `<button class="tab ${state.inspector === tab ? "active" : ""}" data-tab="${tab}">${tab[0].toUpperCase() + tab.slice(1)}</button>`).join("")}</nav><div class="inspector-body" id="inspector-body"></div>
      <div class="inspector-actions"><button class="button" id="save-clip" disabled>Save changes</button><button class="button primary" id="export-clip">${clip.video_url ? "Export again ↗" : "Export clip ↗"}</button>
      ${["checked", "ready"].includes(clip.status) ? `<a class="button" href="${clip.video_url}?download=true">↓ Download checked clip</a>${clip.status === "checked" ? '<button class="button primary" id="approve-clip">✓ Approve for guest kit</button>' : '<span class="render-hint">Approved by you. Included in the guest kit.</span>'}` : '<span class="render-hint">Finished files are checked before they enter your guest kit.</span>'}</div></aside></section>`
        : `<section class="empty-moments"><span class="eyebrow">LET THE CONVERSATION DO THE TALKING</span><h2>Find something worth keeping.</h2><p>${p.words.length ? "Your transcript is ready. Find moments automatically, or choose a continuous excerpt yourself." : "Transcribe the conversation on your computer, or import an existing timed transcript."}</p><div class="empty-actions"><button class="button primary" id="${p.words.length ? "add-moment" : "transcribe-now"}">${p.words.length ? "＋ Add a moment" : "Transcribe locally"}</button><button class="button" id="import-transcript">Import SRT or word JSON</button></div></section>`
    }
    <section class="words-panel"><div class="words-heading"><div><span class="eyebrow">THE ORIGINAL WORDS</span><h2>${p.words.length ? "Follow the thought." : "Start with a transcript."}</h2></div><div class="button-row"><button class="button small" id="import-transcript-bottom">Import transcript</button>${!p.words.length ? '<button class="button small" id="transcribe-bottom">Transcribe</button>' : ""}</div></div>
    ${p.transcript?.timing === "estimated" ? '<p class="warning-text">SRT word timing is estimated from subtitle rows. Use local transcription for accurate word highlights.</p>' : ""}
    <div class="words-text" id="transcript-words">${p.words.length ? p.words.map((w, i) => `<button class="word ${state.draft && w.start >= state.draft.start && w.end <= state.draft.end ? "selected" : ""}" data-word="${i}" title="Jump to ${clock(w.start)}">${esc(w.text)}</button>`).join(" ") : '<p class="no-words">Local Whisper keeps audio on your computer. Optional cloud transcription is available in Settings.</p>'}</div></section>`;
  $("#back-library").onclick = () => action(library);
  $("#find-moments").onclick = () =>
    action(async () => {
      if (!state.status.providers.openai) {
        await settings();
        toast(
          "Automatic selection needs your OpenAI key. Manual selection works offline.",
        );
        return;
      }
      await startJob("analyze");
    });
  $("#download-kit").onclick = (event) => {
    if (!ready) {
      event.preventDefault();
      toast("Review and approve a checked clip to build its guest kit.");
    }
  };
  $("#add-moment")?.addEventListener("click", showMoment);
  for (const selector of ["#import-transcript", "#import-transcript-bottom"])
    $(selector)?.addEventListener("click", () => $("#transcript-file").click());
  for (const selector of ["#transcribe-now", "#transcribe-bottom"])
    $(selector)?.addEventListener("click", () =>
      action(() => startJob("transcribe")),
    );
  $$("[data-clip]").forEach(
    (button) =>
      (button.onclick = () =>
        action(async () => {
          await saveClip(false);
          state.clipId = button.dataset.clip;
          state.draft = clipInput(currentClip());
          state.dirty = false;
          state.playhead = state.draft.start;
          state.previewMode = currentClip().video_url ? "export" : "layout";
          location.hash = `project=${p.id}&clip=${state.clipId}`;
          renderProject();
        })),
  );
  $$("[data-tab]").forEach(
    (button) =>
      (button.onclick = () => {
        state.inspector = button.dataset.tab;
        $$("[data-tab]").forEach((b) =>
          b.classList.toggle("active", b === button),
        );
        renderInspector();
      }),
  );
  if (clip) {
    $("#clip-title").addEventListener("input", (event) => {
      state.draft.title = event.target.value;
      dirty();
      renderPreview();
    });
    $("#save-clip").onclick = () => action(() => saveClip());
    $("#export-clip").onclick = () =>
      action(async () => {
        await saveClip(false);
        await startJob("render", state.clipId);
      });
    $("#approve-clip")?.addEventListener("click", () =>
      action(async () => {
        await saveClip(false);
        await request(`/api/projects/${p.id}/clips/${state.clipId}/approve`, {
          method: "POST",
        });
        await openProject(p.id, state.clipId);
        toast("Approved. This clip is now in the guest kit.");
      }),
    );
    $("#play-selection").onclick = () =>
      action(async () => {
        const video =
          state.previewMode === "export"
            ? $("#exported-video")
            : $("#source-video");
        if (!video) return;
        if (video.paused) {
          if (
            state.previewMode === "layout" &&
            (video.currentTime < state.draft.start ||
              video.currentTime >= state.draft.end)
          )
            video.currentTime = state.draft.start;
          await video.play();
          $("#play-selection").textContent = "Ⅱ";
        } else {
          video.pause();
          $("#play-selection").textContent = "▶";
        }
      });
    $("#playhead-range").oninput = (event) => {
      state.playhead = Number(event.target.value);
      const video = $("#source-video");
      if (video) video.currentTime = state.playhead;
      $("#playhead-time").textContent =
        `${clock(state.playhead)} / ${clock(p.duration)}`;
    };
    $("#toggle-preview").onclick = () => {
      if (!currentClip().video_url) {
        toast(
          "This preview uses the original recording. Export to watch the finished composition.",
        );
        return;
      }
      state.previewMode = state.previewMode === "export" ? "layout" : "export";
      renderPreview();
    };
    renderInspector();
    renderPreview();
  }
  $$("[data-word]").forEach(
    (button) =>
      (button.onclick = () => {
        const word = p.words[Number(button.dataset.word)];
        state.playhead = word.start;
        if (state.previewMode === "export") {
          state.previewMode = "layout";
          renderPreview();
        }
        const video = $("#source-video");
        if (video) video.currentTime = word.start;
        if ($("#playhead-range")) $("#playhead-range").value = word.start;
      }),
  );
  renderJobs();
}

function field(label, id, value, type = "text", extra = "") {
  return `<label class="field">${label}<input id="${id}" type="${type}" value="${esc(value)}" ${extra}></label>`;
}
function renderInspector() {
  const d = state.draft,
    c = currentClip(),
    p = state.project,
    body = $("#inspector-body");
  if (!d || !body) return;
  if (state.inspector === "style") {
    body.innerHTML = `<div class="control-block"><div class="control-label">A look that feels like you</div><div class="template-grid">${[
      "editorial",
      "paper",
      "focus",
    ]
      .map(
        (template) =>
          `<button class="template-button ${d.style.template === template ? "active" : ""}" data-template="${template}"><div class="mini-template ${template}"><div class="mini-title">A thought<br>worth keeping.</div><div class="mini-frame"></div><div class="mini-caption">Make it yours.</div></div>${template[0].toUpperCase() + template.slice(1)}</button>`,
      )
      .join("")}</div></div>
    <div class="control-block"><div class="control-label">Made for the feed</div><div class="segmented">${["9:16", "4:5"].map((r) => `<button data-ratio="${r}" class="${d.style.ratio === r ? "active" : ""}">${r === "9:16" ? "9:16 · Reels / Shorts" : "4:5 · Feed"}</button>`).join("")}</div></div>
    <div class="control-block"><div class="control-label">Your accent colour</div><div class="color-row">${["#F36B45", "#A9C46C", "#719FE5", "#B0A0D3", "#D4AA48"].map((color) => `<button class="swatch ${state.brand.accent.toLowerCase() === color.toLowerCase() ? "active" : ""}" data-color="${color}" style="--swatch:${color}" aria-label="Use ${color}"></button>`).join("")}<input class="color-picker" id="accent-color" type="color" value="${state.brand.accent}" aria-label="Custom accent colour"></div></div>
    <div class="control-block"><label class="toggle-row">Word-by-word captions<input id="captions-toggle" type="checkbox" ${d.style.captions ? "checked" : ""}></label><label class="toggle-row">A closing thought<input id="endcard-toggle" type="checkbox" ${state.brand.end_card ? "checked" : ""}></label></div>
    <div class="control-block"><div class="control-label">Source framing</div><div class="segmented">${["fit", "fill"].map((f) => `<button data-framing="${f}" class="${d.style.framing === f ? "active" : ""}">${f === "fit" ? "Keep full frame" : "Fill the window"}</button>`).join("")}</div>
      ${d.style.framing === "fill" ? `<label class="field" style="margin:15px 0 0">Horizontal focus<input id="focal-x" type="range" min="0" max="1" step=".01" value="${d.style.focal_x}"></label><p class="micro">Check the whole excerpt so neither speaker is cropped out.</p>` : ""}</div>
    <details><summary>Your show identity</summary>${field("Show name", "brand-show", state.brand.show, "text", 'maxlength="60"')}${field("Guest name", "brand-guest", state.brand.guest, "text", 'maxlength="60"')}${field("Guest role", "brand-role", state.brand.role, "text", 'maxlength="90"')}</details>`;
    $$("[data-template]").forEach(
      (b) =>
        (b.onclick = () => {
          d.style.template = b.dataset.template;
          dirty();
          renderInspector();
          renderPreview();
        }),
    );
    $$("[data-ratio]").forEach(
      (b) =>
        (b.onclick = () => {
          d.style.ratio = b.dataset.ratio;
          dirty();
          renderInspector();
          renderPreview();
        }),
    );
    $$("[data-framing]").forEach(
      (b) =>
        (b.onclick = () => {
          d.style.framing = b.dataset.framing;
          dirty();
          renderInspector();
          renderPreview();
        }),
    );
    $$("[data-color]").forEach(
      (b) =>
        (b.onclick = () => {
          state.brand.accent = b.dataset.color;
          dirty();
          renderInspector();
          renderPreview();
        }),
    );
    $("#accent-color").oninput = (e) => {
      state.brand.accent = e.target.value;
      dirty();
      renderPreview();
    };
    $("#captions-toggle").onchange = (e) => {
      d.style.captions = e.target.checked;
      dirty();
      renderPreview();
    };
    $("#endcard-toggle").onchange = (e) => {
      state.brand.end_card = e.target.checked;
      dirty();
    };
    $("#focal-x")?.addEventListener("input", (e) => {
      d.style.focal_x = Number(e.target.value);
      dirty();
      const video = $("#source-video");
      if (video) video.style.objectPosition = `${d.style.focal_x * 100}% 50%`;
    });
    for (const key of ["show", "guest", "role"])
      $("#brand-" + key).oninput = (e) => {
        state.brand[key] = e.target.value;
        dirty();
        renderPreview();
      };
  } else if (state.inspector === "words") {
    body.innerHTML = `<div class="control-block"><div class="control-label">Keep the whole thought</div><div class="two-fields">${field("Start · seconds", "clip-start", d.start, "number", 'min="0" step=".01"')}${field("End · seconds", "clip-end", d.end, "number", 'min="5" step=".01"')}</div><div class="range-help">${Math.round((d.end - d.start) * 10) / 10}s · original, continuous speech</div><div class="button-row" style="margin-top:12px"><button class="button small" id="use-start">Start at playhead</button><button class="button small" id="use-end">End at playhead</button></div></div>
      <label class="field">The closing thought<textarea id="clip-takeaway" maxlength="140">${esc(d.takeaway)}</textarea></label>
      <label class="field">A few words to go with it<textarea id="clip-post" rows="6" maxlength="3000">${esc(d.post)}</textarea></label>
      <p class="micro">${esc(c.editorial?.method || "Selected by you")}. ${esc(d.reason)}</p><button class="button text danger" id="delete-clip" style="margin-top:20px">Remove this moment</button>`;
    for (const key of ["start", "end"])
      $("#clip-" + key).oninput = (e) => {
        d[key] = Number(e.target.value);
        dirty();
        updateWordHighlights();
      };
    $("#use-start").onclick = () => {
      d.start = Math.round(state.playhead * 100) / 100;
      dirty();
      renderInspector();
      updateWordHighlights();
    };
    $("#use-end").onclick = () => {
      d.end = Math.round(state.playhead * 100) / 100;
      dirty();
      renderInspector();
      updateWordHighlights();
    };
    $("#clip-takeaway").oninput = (e) => {
      d.takeaway = e.target.value;
      dirty();
    };
    $("#clip-post").oninput = (e) => {
      d.post = e.target.value;
      dirty();
    };
    $("#delete-clip").onclick = () =>
      action(async () => {
        await request(`/api/projects/${p.id}/clips/${c.id}`, {
          method: "DELETE",
        });
        state.dirty = false;
        await openProject(p.id);
        toast("Moment removed. Your source video is retained.");
      });
  } else {
    const report = c.report;
    body.innerHTML = report
      ? `<p class="check-intro">${report.pass ? "These checks passed on the actual encoded file. Watch the clip before approving it." : "The export is held for review. Resolve these checks, then export again."}</p><div class="check-list">${report.checks.map((check) => `<div class="check-row ${check.status === "pass" ? "" : "fail"}"><span class="check-icon">${check.status === "pass" ? "✓" : "!"}</span><div>${esc(check.label)}<small>${esc(check.message || (check.id === "speech" ? `Speech match ${Math.round(check.details.speech_match * 100)}% · checked locally` : check.id === "media" ? `${check.details.width} × ${check.details.height} · ${check.details.duration.toFixed(2)}s` : check.id === "loudness" ? `${check.details.integrated_lufs} LUFS · ${check.details.true_peak_dbtp} dBTP` : "Passed"))}</small></div></div>`).join("")}</div>
      <div class="button-row" style="margin-top:24px"><a class="button small" href="${c.sheet_url}" target="_blank">Inspect frames ↗</a><a class="button small" href="/api/projects/${p.id}/clips/${c.id}/assets/report.json?download=true">Check report ↓</a></div><p class="check-note">${report.render_reused ? "The existing encoded export was reused and checked again. " : ""}Technical checks support your judgment. They do not prove editorial quality or predict views.</p>`
      : `<p class="check-intro">The export is checked before it can enter a guest kit.</p><div class="check-list">${["Complete video and correct dimensions", "Original-voice audio and continuity", "Readable headline and captions", "Speech matches the selected words", "Show identity and end card"].map((label) => `<div class="check-row"><span class="check-icon" style="color:#a0aa92">○</span><div>${label}<small>Checked on export</small></div></div>`).join("")}</div><p class="check-note">Your original speech is kept in one continuous excerpt. No generated narration is added to your clips.</p>`;
    if (state.dirty)
      body.insertAdjacentHTML(
        "afterbegin",
        '<p class="warning-text" style="margin-bottom:18px">You have unsaved changes. Previous checks do not apply to the edited version.</p>',
      );
  }
}

function fitText(text, width, height, maxSize, maxLines = 3) {
  const canvas = document.createElement("canvas"),
    ctx = canvas.getContext("2d");
  for (let size = maxSize; size >= 24; size -= 2) {
    ctx.font = `800 ${size}px Bricolage`;
    const lines = [];
    let line = "",
      wide = false;
    for (const word of text.split(/\s+/)) {
      if (ctx.measureText(word).width > width) wide = true;
      const next = line ? line + " " + word : word;
      if (line && ctx.measureText(next).width > width) {
        lines.push(line);
        line = word;
      } else line = next;
    }
    if (line) lines.push(line);
    if (
      !wide &&
      lines.length <= maxLines &&
      lines.length * size * 1.08 <= height
    )
      return { lines, size };
  }
  return { lines: [text], size: 24 };
}
function rect(element, box) {
  Object.assign(element.style, {
    left: box[0] + "px",
    top: box[1] + "px",
    width: box[2] + "px",
    height: box[3] + "px",
  });
}
function renderPreview() {
  const holder = $("#preview-holder");
  if (!holder || !state.draft) return;
  previewObserver?.disconnect();
  const d = state.draft,
    p = state.project,
    c = currentClip(),
    brand = state.brand,
    vertical = d.style.ratio === "9:16";
  if (state.previewMode === "export" && c.video_url && !state.dirty) {
    holder.innerHTML = `<video id="exported-video" class="exported-video" src="${c.video_url}" poster="${c.cover_url}" controls playsinline preload="metadata"></video>`;
    $("#preview-label").textContent =
      c.status === "needs_review"
        ? "ENCODED EXPORT · NEEDS REVIEW"
        : "ENCODED EXPORT";
    $("#preview-note").textContent =
      c.status === "needs_review"
        ? "This export has failed checks. Review the report before sharing."
        : "You are watching the actual encoded export. Creative approval is yours.";
    $("#exported-video").onpause = () =>
      ($("#play-selection").textContent = "▶");
    return;
  }
  const oldVideo = $("#source-video");
  if (oldVideo && Number.isFinite(oldVideo.currentTime))
    state.playhead = oldVideo.currentTime;
  const paper = d.style.template === "paper",
    focus = d.style.template === "focus",
    height = vertical ? 1920 : 1350;
  const fg = paper ? "#20261e" : "#f5f1e7",
    bg = paper ? "#f1eee6" : "#101310";
  const layout = state.status.layouts[d.style.ratio][d.style.template];
  const title = fitText(
    d.title,
    layout.title[2],
    layout.title[3],
    vertical ? 102 : 82,
  );
  holder.innerHTML = `<div class="preview-viewport" style="aspect-ratio:1080/${height}"><div class="composition" style="height:${height}px;background:${bg};color:${fg}">
    <div class="comp-position comp-video"><video id="source-video" src="${p.source_url_local}" preload="metadata" playsinline style="object-fit:${d.style.framing === "fill" ? "cover" : "contain"};object-position:${d.style.focal_x * 100}% 50%"></video>
    ${!focus ? `<div class="comp-guest" style="font-size:${vertical ? 30 : 27}px">${esc(brand.guest)}${brand.role ? `<small style="font-size:${vertical ? 23 : 20}px">${esc(brand.role)}</small>` : ""}</div>` : ""}</div>
    <div class="comp-position comp-header" style="font-size:${vertical ? 32 : 27}px"><span>${esc(brand.show)}</span><small style="color:${brand.accent}">${paper ? "01 /" : "EXCERPT"}</small></div>
    <div class="comp-position comp-title" style="font-size:${title.size}px;letter-spacing:${-title.size * 0.025}px">${title.lines.map((line) => `<div>${esc(line)}</div>`).join("")}${paper ? `<div style="width:108px;height:7px;background:${brand.accent};margin-top:24px"></div>` : ""}</div>
    <div class="comp-position comp-caption" id="preview-caption"></div><div class="comp-position comp-footer" style="font-size:${vertical ? 23 : 20}px;color:${paper ? "#686d60" : "#a5aa9d"}"><span>THE FULL CONVERSATION IS WORTH IT.</span><span style="color:${brand.accent}">↗</span></div>
    </div></div>`;
  const composition = $(".composition");
  for (const key of ["video", "header", "title", "captions", "footer"])
    rect($(".comp-" + (key === "captions" ? "caption" : key)), layout[key]);
  if (focus)
    for (const key of ["header", "title"])
      Object.assign($(".comp-" + key).style, {
        background: "rgba(12,18,13,.88)",
        padding: "15px 22px",
        color: "#faf7ee",
      });
  const viewport = $(".preview-viewport");
  const scale = () =>
    (composition.style.transform = `scale(${viewport.clientWidth / 1080})`);
  previewObserver = new ResizeObserver(scale);
  previewObserver.observe(viewport);
  scale();
  $("#preview-label").textContent = "LAYOUT PREVIEW";
  $("#preview-note").textContent = p.sample
    ? "Synthetic narration and original artwork. Export to inspect the finished file."
    : "Original footage and speech. Export checks run on the finished file.";
  const video = $("#source-video");
  video.onloadedmetadata = () => {
    video.currentTime = Math.min(
      p.duration - 0.05,
      Math.max(0, state.playhead || d.start),
    );
    updateCaption(video.currentTime);
  };
  video.ontimeupdate = () => {
    state.playhead = video.currentTime;
    $("#playhead-time").textContent =
      `${clock(state.playhead)} / ${clock(p.duration)}`;
    $("#playhead-range").value = state.playhead;
    updateCaption(state.playhead);
    if (!video.paused && video.currentTime >= d.end) {
      video.pause();
      $("#play-selection").textContent = "▶";
    }
  };
  video.onpause = () => ($("#play-selection").textContent = "▶");
  updateCaption(state.playhead);
}
function captionGroups(words) {
  const result = [];
  let group = [];
  for (const word of words) {
    const previous = group.at(-1);
    if (
      group.length &&
      (group.length >= 3 ||
        group.map((w) => w.text).join(" ").length + word.text.length > 22 ||
        /[.?!,]["”]?$/.test(previous.text) ||
        word.start - previous.end > 0.3 ||
        word.speaker !== previous.speaker)
    ) {
      result.push(group);
      group = [];
    }
    group.push(word);
  }
  if (group.length) result.push(group);
  return result;
}
function updateCaption(time) {
  const element = $("#preview-caption");
  if (!element || !state.draft) return;
  const d = state.draft;
  const words = state.project.words.filter(
      (w) => w.start >= d.start - 0.03 && w.end <= d.end + 0.03,
    ),
    groups = captionGroups(words);
  const group = [...groups]
    .reverse()
    .find((g) => time >= g[0].start - 0.025 && time <= g.at(-1).end + 0.13);
  if (!group || !d.style.captions) {
    element.innerHTML = "";
    return;
  }
  const box = state.status.layouts[d.style.ratio][d.style.template].captions,
    fit = fitText(
      group.map((w) => w.text).join(" "),
      box[2] - 32,
      box[3],
      d.style.ratio === "9:16" ? 96 : 82,
      2,
    );
  const focus = d.style.template === "focus";
  element.innerHTML = `<div style="font-size:${fit.size}px;letter-spacing:${-fit.size * 0.025}px;${focus ? "background:rgba(12,18,13,.92);padding:15px 24px;border-radius:12px;color:#faf7ee" : ""}">${group.map((word) => `<span style="${time >= word.start - 0.025 && time <= word.end + 0.04 ? "color:" + state.brand.accent : ""}">${esc(word.text)}</span>`).join(" ")}</div>`;
}
function updateWordHighlights() {
  $$("[data-word]").forEach((button) => {
    const w = state.project.words[Number(button.dataset.word)];
    button.classList.toggle(
      "selected",
      w.start >= state.draft.start && w.end <= state.draft.end,
    );
  });
}
async function saveClip(notify = true) {
  if (!state.dirty || !state.project || !state.draft) return;
  const id = state.project.id,
    clipId = state.clipId;
  if (JSON.stringify(state.brand) !== JSON.stringify(state.project.brand))
    await request(`/api/projects/${id}`, {
      method: "PUT",
      body: { title: state.project.title, brand: state.brand },
    });
  await request(`/api/projects/${id}/clips/${clipId}`, {
    method: "PUT",
    body: state.draft,
  });
  state.dirty = false;
  state.project = await request(`/api/projects/${id}`);
  state.brand = structuredClone(state.project.brand);
  state.draft = clipInput(currentClip());
  if (notify) {
    renderProject();
    toast("Changes saved. Export to check this version.");
  }
}
async function startJob(kind, clipId = null) {
  if (state.dirty) await saveClip(false);
  const job = await request(
    `/api/projects/${state.project.id}/jobs/${kind}${clipId ? "?clip_id=" + clipId : ""}`,
    { method: "POST" },
  );
  state.project.jobs.unshift(job);
  state.lastJob = job.id + ":" + job.status;
  renderJobs();
  toast(
    kind === "render"
      ? "Export queued. You can follow its progress here."
      : "The editor is working on your conversation.",
  );
}
function renderJobs() {
  const container = $("#jobs");
  if (!container || !state.project) return;
  const job = activeJob() || state.project.jobs[0];
  if (!job || job.status === "completed") {
    container.innerHTML = "";
    setBusy(false);
    return;
  }
  const busy = ["queued", "running", "cancelling"].includes(job.status);
  setBusy(busy);
  container.innerHTML = `<div class="job-strip ${["failed", "interrupted"].includes(job.status) ? "failed" : ""}"><div class="job-message"><strong>${esc(job.stage)}</strong><small>${esc(job.error || (job.status === "cancelling" ? "Stopping. A provider request already in progress may need to finish." : busy ? "Completed work is saved as the editor progresses." : "Your source and saved exports are retained."))}</small></div>
    ${
      busy
        ? `<div class="progress-track" aria-label="Production progress"><span style="width:${Math.max(3, job.progress * 100)}%"></span></div><button class="button small" id="stop-job" ${job.status === "cancelling" ? "disabled" : ""}>Stop</button>`
        : `<button class="button small" id="retry-job">Retry</button>`
    }</div>`;
  $("#stop-job")?.addEventListener("click", () =>
    action(async () => {
      await request(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      await poll();
    }),
  );
  $("#retry-job")?.addEventListener("click", () =>
    action(() => startJob(job.kind, job.clip_id)),
  );
}
function setBusy(busy) {
  for (const selector of [
    "#find-moments",
    "#export-clip",
    "#save-clip",
    "#approve-clip",
    "#add-moment",
  ]) {
    const element = $(selector);
    if (element)
      element.disabled = busy || (selector === "#save-clip" && !state.dirty);
  }
}
async function poll() {
  if (pollBusy || !state.project || state.view !== "project") return;
  pollBusy = true;
  try {
    const fresh = await request(`/api/projects/${state.project.id}`);
    const signature = fresh.jobs[0]?.id + ":" + fresh.jobs[0]?.status;
    if (
      signature !== state.lastJob &&
      ["completed", "failed", "cancelled", "interrupted"].includes(
        fresh.jobs[0]?.status,
      ) &&
      !state.dirty
    ) {
      state.project = fresh;
      state.lastJob = signature;
      state.brand = structuredClone(fresh.brand);
      state.clipId = fresh.clips.some((c) => c.id === state.clipId)
        ? state.clipId
        : fresh.clips[0]?.id;
      state.draft = currentClip() ? clipInput(currentClip()) : null;
      if (fresh.jobs[0].kind === "render" && currentClip()?.video_url)
        state.previewMode = "export";
      renderProject();
      if (fresh.jobs[0].status === "completed")
        toast(
          currentClip()?.status === "needs_review"
            ? "Export finished with checks that need review."
            : "Work saved. Ready for your review.",
        );
    } else {
      state.project.jobs = fresh.jobs;
      renderJobs();
    }
  } catch (error) {
    const container = $("#jobs");
    if (container && !container.textContent.includes("Connection lost"))
      container.insertAdjacentHTML(
        "beforeend",
        '<p class="micro" style="margin:0 32px 16px">Connection lost. Showing the last confirmed state; reconnecting…</p>',
      );
  } finally {
    pollBusy = false;
  }
}

async function settings() {
  if (state.dirty) await saveClip(false);
  const status = await request("/api/status");
  state.status = status;
  setNavigation("settings");
  location.hash = "settings";
  $("#breadcrumbs").innerHTML = "Your studio <span>/</span> Settings";
  const s = status.settings;
  $("#content").innerHTML =
    `<section class="settings-page"><span class="eyebrow">YOUR TOOLS. YOUR CHOICES.</span><h1>Make yourself at home.</h1><p>Run the work locally. Connect a provider when you want a second pair of editorial eyes.</p><form id="settings-form">
    <section class="settings-section"><div><h2>Editorial selection</h2><p>Automatic moment selection sends transcript text to OpenAI. Manual selection works without a key.</p></div><div>
    <label class="field">OpenAI API key ${status.providers.openai ? '<span class="tag good">Configured · value hidden</span>' : ""}<input id="openai-key" type="password" autocomplete="off" placeholder="${status.providers.openai ? "Leave blank to keep the current key" : "sk-…"}"></label>
    ${field("Editorial model", "editor-model", s.editor_model)}<p class="micro">Use a model that supports the Responses API and strict structured outputs.</p></div></section>
    <section class="settings-section"><div><h2>Speech to words</h2><p>Local Whisper keeps the recording on this computer. Cloud transcription sends audio to ElevenLabs.</p></div><div>
    <label class="field">Transcription provider<select id="transcription-provider"><option value="local" ${s.transcription === "local" ? "selected" : ""}>Local Whisper · no API fee</option><option value="elevenlabs" ${s.transcription === "elevenlabs" ? "selected" : ""}>ElevenLabs Scribe · your API key</option></select></label>
    <label class="field">ElevenLabs API key ${status.providers.elevenlabs ? '<span class="tag good">Configured · value hidden</span>' : ""}<input id="elevenlabs-key" type="password" autocomplete="off" placeholder="Leave blank to keep the current key"></label>
    <div class="two-fields">${field("Language code", "language-code", s.language, "text", 'maxlength="3"')}${field("Whisper model", "whisper-model", s.whisper_model)}</div>
    <p class="warning-text">This release verifies English typography and OCR. Other speech languages are experimental. Use a multilingual Whisper model for languages other than English.</p></div></section>
    <section class="settings-section"><div><h2>Your editorial defaults</h2><p>Keep the useful thought intact. You make the final sharing decision.</p></div><div>${field("Moments per conversation", "clip-count", s.clips_per_episode, "number", 'min="1" max="8"')}
    <label class="toggle-row">Exclude profanity<input id="exclude-profanity" type="checkbox" ${s.exclude_profanity ? "checked" : ""}></label></div></section>
    <section class="settings-section"><div><h2>Local setup</h2><p>Renderer and export checks use these tools on your computer.</p></div><div class="tool-list">${Object.entries(
      status.tools,
    )
      .map(
        ([name, exists]) =>
          `<span class="tool ${exists ? "" : "missing"}">${exists ? "✓" : "!"} ${name}</span>`,
      )
      .join(
        "",
      )}<span class="tool ${status.local_speech ? "" : "missing"}">${status.local_speech ? "✓" : "!"} Local speech check</span></div></section>
    <div class="button-row"><button class="button primary" type="submit">Save settings</button><button class="button" type="button" id="return-project">${state.project ? "Back to conversation" : "Back to conversations"}</button></div>
    <div class="privacy-note">Keys are saved only in your local data directory with restricted file permissions. They are never included in guest kits. No analytics or automatic social publishing. API usage is recorded as tokens or audio duration; it is not a provider invoice.<br><a href="https://www.remotion.dev/docs/license/pricing" target="_blank" rel="noreferrer">The renderer has separate Remotion license terms ↗</a></div></form></section>`;
  $("#settings-form").onsubmit = (event) => {
    event.preventDefault();
    action(async () => {
      await request("/api/settings", {
        method: "PUT",
        body: {
          settings: {
            editor_model: $("#editor-model").value,
            transcription: $("#transcription-provider").value,
            language: $("#language-code").value,
            whisper_model: $("#whisper-model").value,
            exclude_profanity: $("#exclude-profanity").checked,
            clips_per_episode: Number($("#clip-count").value),
          },
          openai_key: $("#openai-key").value || null,
          elevenlabs_key: $("#elevenlabs-key").value || null,
        },
      });
      state.status = await request("/api/status");
      toast("Local settings saved.");
      $("#openai-key").value = "";
      $("#elevenlabs-key").value = "";
    });
  };
  $("#return-project").onclick = () =>
    action(() =>
      state.project ? openProject(state.project.id, state.clipId) : library(),
    );
}

function showImport() {
  $("#import-dialog").showModal();
  $("#import-progress").hidden = true;
  $("#youtube-url").value = "";
  $("#video-file").value = "";
  $("#import-submit").disabled = false;
}
function showMoment() {
  if (activeJob()) {
    toast("Finish or stop the current work before adding a moment.");
    return;
  }
  const form = $("#moment-form");
  form.reset();
  form.elements.start.value =
    Math.round(Math.max(0, state.playhead) * 100) / 100;
  form.elements.end.value =
    Math.round(Math.min(state.project.duration, state.playhead + 30) * 100) /
    100;
  $("#moment-dialog").showModal();
}
function upload(path, file, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader("X-Goodtake", "1");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onload = () => {
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        reject(new Error("The import did not finish. Try again."));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else
        reject(
          new Error(
            typeof data.detail === "string"
              ? data.detail
              : "The file could not be imported.",
          ),
        );
    };
    xhr.onerror = () => reject(new Error("Connection lost during import."));
    xhr.send(form);
  });
}
$("#import-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const button = $("#import-submit"),
      progress = $("#import-progress"),
      file = $("#video-file").files[0],
      url = $("#youtube-url").value.trim();
    if (!file && !url) {
      toast("Choose a video or paste a YouTube link.", true);
      return;
    }
    button.disabled = true;
    progress.hidden = false;
    progress.textContent = file
      ? "Importing the original video…"
      : "Downloading from YouTube. This can take several minutes…";
    try {
      const project = file
        ? await upload(
            "/api/projects/upload",
            file,
            (value) =>
              (progress.textContent =
                value < 1
                  ? `Importing video · ${Math.round(value * 100)}%`
                  : "Checking the source video…"),
          )
        : await request("/api/projects/youtube", {
            method: "POST",
            body: { url },
          });
      $("#import-dialog").close();
      state.projects = await request("/api/projects");
      await openProject(project.id);
      toast("Conversation imported. Your original stays local.");
    } finally {
      button.disabled = false;
    }
  });
};
$("#video-file").onchange = () => {
  const file = $("#video-file").files[0];
  if (file) {
    $(".upload-zone strong").textContent = file.name;
    $("#youtube-url").value = "";
  }
};
$("#moment-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const form = event.target;
    const project = await request(`/api/projects/${state.project.id}/clips`, {
      method: "POST",
      body: {
        title: form.elements.title.value,
        start: Number(form.elements.start.value),
        end: Number(form.elements.end.value),
      },
    });
    $("#moment-dialog").close();
    await openProject(project.id, project.clips.at(-1).id);
    state.inspector = "words";
    renderProject();
  });
};
$("#transcript-file").onchange = () =>
  action(async () => {
    const file = $("#transcript-file").files[0];
    if (!file || !state.project) return;
    const project = await upload(
      `/api/projects/${state.project.id}/transcript`,
      file,
    );
    state.dirty = false;
    await openProject(project.id, state.clipId);
    toast(
      file.name.endsWith(".srt")
        ? "Transcript imported. Word timing from SRT is approximate."
        : "Timed words imported.",
    );
    $("#transcript-file").value = "";
  });
$$("[data-close]").forEach(
  (button) => (button.onclick = () => button.closest("dialog").close()),
);
$("#new-project").onclick = showImport;
$("#library-nav").onclick = () => action(library);
$("#settings-nav").onclick = () => action(settings);
$(".wordmark").onclick = (event) => {
  event.preventDefault();
  action(library);
};
window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("hashchange", () =>
  action(async () => {
    const hash = new URLSearchParams(location.hash.slice(1));
    if (location.hash === "#settings" && state.view !== "settings")
      await settings();
    else if (
      hash.has("project") &&
      (state.view !== "project" ||
        state.project?.id !== hash.get("project") ||
        state.clipId !== hash.get("clip"))
    )
      await openProject(hash.get("project"), hash.get("clip"));
    else if (!location.hash && state.view !== "library") await library();
  }),
);
async function initialize() {
  await document.fonts.ready;
  [state.status, state.projects] = await Promise.all([
    request("/api/status"),
    request("/api/projects"),
  ]);
  const hash = new URLSearchParams(location.hash.slice(1));
  if (location.hash === "#settings") await settings();
  else if (hash.has("project"))
    await openProject(hash.get("project"), hash.get("clip"));
  else await library();
  setInterval(poll, 1800);
}
action(initialize);
