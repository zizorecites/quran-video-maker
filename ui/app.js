/* Quran Video Maker - the screens.  by @zizorecites */
(function () {
  "use strict";

  // ------------------------------------------------------------ helpers
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const clock = (t, tenths) => {
    t = Math.max(0, t || 0);
    const m = Math.floor(t / 60), s = t - m * 60;
    return tenths ? `${m}:${s.toFixed(1).padStart(4, "0")}` : `${m}:${String(Math.floor(s)).padStart(2, "0")}`;
  };
  const isNumberToken = (w) => /^[٠-٩۝]+$/.test(w);

  async function api(name, args) {
    const r = await fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": window.QVM_TOKEN },
      body: JSON.stringify(args || {}),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "Something went wrong.");
    return j.data;
  }

  let toastTimer = null;
  function toast(msg, bad) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = bad ? "bad" : "";
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), bad ? 6000 : 2600);
  }
  async function attempt(fn) {
    try { return await fn(); } catch (e) { toast(e.message, true); }
  }

  const ICON = {
    audio: '<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
    video: '<svg viewBox="0 0 24 24"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="M16 10l6-3v10l-6-3"/></svg>',
  };

  // ------------------------------------------------------------- state
  let S = null;              // everything the backend knows, refreshed often
  let view = "make";
  let lastSig = "";
  let dragDepth = 0;
  let setupSkipped = false;

  async function refresh() {
    try {
      S = await api("state");
    } catch (e) {
      return;
    }
    const running = S.run.active;
    const badge = $("#nav-running");
    badge.hidden = !running;
    badge.title = running ? "Making videos" : "";
    if (!S.setup.ready && !setupSkipped) {
      if (view !== "setup") { view = "setup"; lastSig = ""; }
    } else if (view === "setup") {
      view = "make"; lastSig = "";
    }
    if (running && view === "make") { view = "making"; lastSig = ""; }
    $$(".nav").forEach((n) => n.classList.toggle("on", n.dataset.view === (view === "making" ? "make" : view === "editor" ? "finished" : view)));
    const sig = JSON.stringify([view, view === "setup" ? S.setup : null,
      (view === "make") ? [S.items, S.settings.bg_url, S.settings.skip_done] : null,
      (view === "making") ? S.run : null]);
    if (sig !== lastSig) {
      lastSig = sig;
      render();
    }
  }
  window.app = { refresh: () => { lastSig = ""; return refresh(); } };

  function go(v) {
    view = v;
    lastSig = "";
    render();
    refresh();
  }

  function render() {
    const m = $("#main");
    if (view === "setup") return renderSetup(m);
    if (view === "make") return renderMake(m);
    if (view === "making") return renderMaking(m);
    if (view === "finished") return renderFinished(m);
    if (view === "settings") return renderSettings(m);
    if (view === "editor") return renderEditor(m);
  }

  // ------------------------------------------------------------- setup
  function renderSetup(m) {
    const st = S.setup;
    const pct = st.total ? Math.round((st.done / st.total) * 100) : 0;
    const mb = (b) => Math.round(b / 1e6);
    let listenRow;
    if (st.error) {
      listenRow = `<div class="steprow"><span class="check"></span><b>Downloading the listener</b><span class="right red">stopped</span></div>
        <div class="red" style="font-size:12.5px">Couldn't download it: ${esc(st.error)}. Check the internet connection and try again.</div>
        <div style="display:flex;gap:8px"><button class="btn small primary" data-act="dl">Try again</button>
        <button class="btn small ghost" data-act="skip">Skip for now</button></div>`;
    } else if (st.downloading || st.done) {
      listenRow = `<div><div class="steprow" style="margin-bottom:9px"><span class="check now"></span><b>Downloading the listener</b>
        <span class="right faint">${mb(st.done)} of ${mb(st.total) || 480} MB</span></div>
        <div class="prog"><i style="width:${pct}%"></i></div>
        <div class="faint" style="font-size:12px;margin-top:6px">The part that hears your recitation. Only needed once.</div></div>`;
    } else {
      listenRow = `<div class="steprow"><span class="check"></span><b>The listener</b><span class="right faint">480 MB</span></div>
        <div class="faint" style="font-size:12.5px">The part that hears your recitation, so each screen shows exactly what you said.</div>
        <div><button class="btn primary" data-act="dl">Download it</button></div>`;
    }
    m.innerHTML = `<div class="setup"><div class="inner">
      <div class="logo">ق</div>
      <h1>Getting ready</h1>
      <p class="muted" style="margin:0 0 26px">This only happens the first time you open the app.</p>
      <div class="card steps">
        <div class="steprow"><span class="check on"></span>Video tools<span class="right faint">included</span></div>
        <div class="steprow"><span class="check on"></span>Mushaf text, Clear Quran translation, word meanings<span class="right faint">included</span></div>
        ${listenRow}
        <div class="steprow ${st.tested ? "" : "faint"}"><span class="check ${st.tested ? "on" : ""}"></span>Quick test run</div>
      </div></div></div>`;
    $$("[data-act=dl]", m).forEach((b) => b.onclick = () => attempt(() => api("download_model")).then(refresh));
    $$("[data-act=skip]", m).forEach((b) => b.onclick = () => { setupSkipped = true; go("make"); });
    if (!st.downloading && !st.done && !st.error && !renderSetup.started) {
      renderSetup.started = true;                 // start straight away
      api("download_model").then(refresh);
    }
  }

  // ------------------------------------------------------------- make videos
  const folderName = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || p;
  function bgChip() {
    const s = S.settings;
    return `<div style="display:flex;align-items:center;gap:10px">
      <div class="thumb" style="width:52px;height:30px;${s.bg_url ? `background-image:url(${s.bg_url})` : "border:1px dashed #445"}"></div>
      <div style="line-height:1.25"><div class="faint" style="font-size:12px">Background for MP3s</div>
      <div style="font-size:13px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.bg_name ? esc(s.bg_name) : "<span class='muted'>none yet</span>"}</div></div>
      <button class="btn small" data-act="bg">${s.bg_name ? "Change" : "Choose…"}</button></div>
      <div style="display:flex;align-items:center;gap:10px;margin-left:18px;min-width:0">
      <div style="line-height:1.25;min-width:0"><div class="faint" style="font-size:12px">Save videos to</div>
      <div style="font-size:13px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(s.out_dir)}">${esc(folderName(s.out_dir))}</div></div>
      <button class="btn small" data-act="out">Change</button></div>`;
  }

  function opt(it, key, label, sub, swatch, disabled) {
    const on = !!it.options[key] && !disabled;
    const made = it.made && it.made[key];
    return `<div class="opt ${on ? "on" : ""} ${disabled ? "off" : ""}" data-opt="${key}" data-id="${it.id}" title="${made ? "Already made" : ""}">
      <span class="check ${on ? "on" : ""}"></span><div class="swatch" style="${swatch}"></div>
      <div style="min-width:0;line-height:1.25"><div class="t">${label}</div><div class="s">${made ? "already made" : sub}</div></div></div>`;
  }

  function wantedVideos(it) {
    const keys = ["black", "bg", "own"].filter((k) => it.options[k]);
    return keys.filter((k) => !(S.settings.skip_done && it.made[k] && !it.again)).filter((k) => k !== "bg" || S.settings.bg_url);
  }

  function renderMake(m) {
    const items = S.items;
    const s = S.settings;
    const bgSw = s.bg_url ? `background-image:url(${s.bg_url})` : "background:#222";
    if (!items.length) {
      m.innerHTML = `<div class="head"><div><h1>Make videos</h1><p>Add recordings. Each one becomes a video with the mushaf text and the English.</p></div></div>
      <div class="content"><div class="drop" id="drop">
        <div class="icons">${ICON.audio}${ICON.video}</div>
        <div style="font-size:20px;font-weight:650">Drop recordings here</div>
        <div class="muted" style="max-width:520px">Audio: <b style="color:var(--ink)">MP3, M4A, WAV</b> &nbsp;·&nbsp; Video of you reciting: <b style="color:var(--ink)">MP4, MOV</b><br>Drop one, a few, or a whole folder.</div>
        <div style="display:flex;gap:10px;margin-top:6px"><button class="btn primary" data-act="files">Choose files…</button><button class="btn" data-act="folder">Choose a folder…</button></div>
        <div class="faint" style="font-size:12.5px;margin-top:10px">Name files like <b class="muted">Mulk7-12.mp3</b> or <b class="muted">Qadr.mp3</b> and it knows the ayahs.</div>
      </div></div>
      <div class="bar">${bgChip()}<div style="margin-left:auto" class="faint">No recordings yet</div><button class="btn primary big" disabled>Make videos</button></div>`;
    } else {
      let total = 0, secs = 0, needs = 0;
      const rows = items.map((it) => {
        const dur = it.duration ? clock(it.duration) : "";
        let ref, status = "", dim = false;
        if (it.status === "failed" && !it.ref) {
          ref = `<span class="red">${esc(it.error || "Can't open this file")}</span>`;
        } else if (!it.ref) {
          ref = `<span class="red" style="font-weight:600">Couldn't tell the ayahs</span>`;
          status = `<button class="btn small primary" data-act="pick" data-id="${it.id}">Pick ayahs</button>`;
          needs++;
        } else {
          ref = `${esc(it.ref.label)} · ${dur}${it.kind === "video" ? " · video" : ""}`;
          status = `<button class="btn small ghost" data-act="pick" data-id="${it.id}">Change ayahs</button>`;
        }
        const w = it.ref ? wantedVideos(it) : [];
        const allMade = it.ref && ["black", "bg", "own"].some((k) => it.options[k]) && w.length === 0 && S.settings.skip_done;
        if (allMade) {
          dim = true;
          status = `<button class="btn small ghost" data-act="again" data-id="${it.id}">Make again</button>`;
        }
        if (it.status === "done") status = `<span class="chip good">✓ made</span>`;
        if (it.status === "failed" && it.ref) status = `<span class="chip bad" title="${esc(it.error)}">didn't work</span>`;
        if (it.status === "stopped") status = `<span class="chip">stopped</span>`;
        total += w.length;
        if (w.length) secs += (it.duration || 60) * (0.6 + 1.0 * w.length);
        const opts = it.kind === "video"
          ? opt(it, "own", "Your video as the background", "exactly as you filmed it", it.thumb ? `background-image:url(${it.thumb})` : "background:#234") +
            opt(it, "black", "Black too", "optional", "background:#000")
          : opt(it, "black", "Black", "guessthesurahz", "background:#000") +
            opt(it, "bg", "With background", s.bg_url ? "your saved background" : "choose a background first", bgSw, !s.bg_url);
        const err = it.status === "failed" && it.ref ? `<div class="red" style="grid-column:1/-1;font-size:12.5px">${esc(it.error)}</div>` : "";
        return `<div class="card row ${dim ? "dim" : ""}">
          <button class="x" data-act="remove" data-id="${it.id}" title="Remove">✕</button>
          <div style="display:flex;gap:11px;align-items:center;min-width:0">
            <div class="ficon ${it.kind === "video" ? "v" : ""}">${ICON[it.kind]}</div>
            <div style="min-width:0"><div class="fname" title="${esc(it.name)}">${esc(it.name)}</div><div class="muted" style="font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${ref}</div></div></div>
          <div style="display:flex;gap:10px;min-width:0">${opts}</div>
          <div style="display:flex;justify-content:flex-end">${status}</div>${err}</div>`;
      }).join("");
      const mins = Math.max(1, Math.round(secs / 60));
      m.innerHTML = `<div class="head"><div><h1>Make videos</h1><p>${items.length} recording${items.length > 1 ? "s" : ""} added. Tick the videos you want for each one.</p></div>
        <div class="right"><button class="btn ghost" data-act="clear">Clear list</button><button class="btn" data-act="files">+ Add more</button></div></div>
        <div class="content"><div class="rows" id="drop">${rows}</div>
        <div class="faint" style="text-align:center;margin-top:16px;font-size:12.5px">Drop more files anywhere in this window.</div></div>
        <div class="bar">${bgChip()}
          <label style="display:flex;gap:8px;align-items:center;margin-left:22px;cursor:pointer" class="muted"><button class="toggle ${s.skip_done ? "on" : ""}" data-act="skip"></button>Skip ones already made</label>
          <div style="margin-left:auto;text-align:right;line-height:1.3"><div style="font-weight:650">${total} video${total !== 1 ? "s" : ""}</div>
          <div class="faint" style="font-size:12px">${needs ? `${needs} still need${needs > 1 ? "" : "s"} ayahs` : total ? `about ${mins} minute${mins > 1 ? "s" : ""}` : "nothing to make"}</div></div>
          <button class="btn primary big" data-act="start" ${total ? "" : "disabled"}>Make videos</button></div>`;
    }
    $$("[data-act=files]", m).forEach((b) => b.onclick = () => attempt(() => api("choose_files")).then(refresh));
    $$("[data-act=folder]", m).forEach((b) => b.onclick = () => attempt(() => api("choose_folder")).then(refresh));
    $$("[data-act=bg]", m).forEach((b) => b.onclick = () => attempt(() => api("choose_background")).then(app.refresh));
    $$("[data-act=out]", m).forEach((b) => b.onclick = () => attempt(() => api("choose_output")).then(app.refresh));
    $$("[data-act=clear]", m).forEach((b) => b.onclick = () => api("clear_items").then(app.refresh));
    $$("[data-act=remove]", m).forEach((b) => b.onclick = () => api("remove_item", { item_id: b.dataset.id }).then(app.refresh));
    $$("[data-act=pick]", m).forEach((b) => b.onclick = () => pickAyahs(S.items.find((i) => i.id === b.dataset.id)));
    $$("[data-act=again]", m).forEach((b) => b.onclick = () => api("make_again", { item_id: b.dataset.id }).then(app.refresh));
    $$("[data-act=skip]", m).forEach((b) => b.onclick = () => api("settings_set", { changes: { skip_done: !S.settings.skip_done } }).then(app.refresh));
    $$("[data-act=start]", m).forEach((b) => b.onclick = () => attempt(() => api("start")).then(() => go("making")));
    $$(".opt", m).forEach((o) => o.onclick = () => {
      if (o.classList.contains("off")) {
        if (o.dataset.opt === "bg") attempt(() => api("choose_background")).then(app.refresh);
        return;
      }
      const it = S.items.find((i) => i.id === o.dataset.id);
      api("set_option", { item_id: it.id, key: o.dataset.opt, value: !it.options[o.dataset.opt] }).then(app.refresh);
    });
  }

  // ------------------------------------------------------------- pick ayahs
  let SURAHS = null;
  async function pickAyahs(it) {
    if (!SURAHS) SURAHS = await api("surahs");
    const ref = it.ref || { surah: 1, first: 1, last: 7 };
    const md = $("#modal");
    md.hidden = false;
    md.innerHTML = `<div class="dialog">
      <h2>Which ayahs are in “${esc(it.name)}”?</h2>
      <div class="muted" style="margin:4px 0 18px">Tip: name the file like <b style="color:var(--ink)">Mulk7-12.mp3</b> and it knows by itself.</div>
      <div style="display:grid;grid-template-columns:1fr 90px 90px;gap:12px;align-items:end">
        <div class="field"><label>Surah</label><select id="p-s">${SURAHS.map((s) => `<option value="${s.n}" ${s.n === ref.surah ? "selected" : ""}>${s.n} · ${esc(s.name)}</option>`).join("")}</select></div>
        <div class="field"><label>From ayah</label><input id="p-a" type="number" min="1" value="${ref.first}"></div>
        <div class="field"><label>To ayah</label><input id="p-b" type="number" min="1" value="${ref.last}"></div>
      </div>
      <div class="faint" id="p-n" style="font-size:12px;margin-top:6px"></div>
      <div class="card" style="margin-top:14px;padding:12px 14px;background:#121917">
        <div class="faint" style="font-size:12px">Starts with</div><div class="ar" id="p-start" style="font-size:21px;white-space:nowrap;overflow:hidden"></div>
        <div class="faint" style="font-size:12px;margin-top:4px">Ends with</div><div class="ar" id="p-end" style="font-size:21px;white-space:nowrap;overflow:hidden"></div>
      </div>
      <label style="display:flex;gap:10px;align-items:center;margin-top:16px;cursor:pointer" class="muted"><span class="check on" id="p-r"></span><span id="p-rl">Rename the file</span></label>
      <div class="actions"><button class="btn" data-act="cancel">Cancel</button><button class="btn primary" data-act="ok">Use these ayahs</button></div></div>`;
    const sel = $("#p-s", md), a = $("#p-a", md), b = $("#p-b", md), r = $("#p-r", md);
    let rename = true;
    const names = () => {
      const s = SURAHS[sel.value - 1];
      const plain = s.name.replace(/^(Al|An|Ar|As|Ash|At|Ad|Adh|Az)-/, "").replace(/ /g, "");
      const whole = +a.value === 1 && +b.value === s.ayahs;
      const ext = it.name.slice(it.name.lastIndexOf("."));
      return whole ? plain + ext : `${plain}${a.value}${+b.value !== +a.value ? "-" + b.value : ""}${ext}`;
    };
    const update = async () => {
      const s = SURAHS[sel.value - 1];
      $("#p-n", md).textContent = `${s.name} has ${s.ayahs} ayahs.`;
      a.max = b.max = s.ayahs;
      $("#p-rl", md).textContent = `Rename the file to ${names()}`;
      if (+a.value < 1 || +b.value < +a.value || +b.value > s.ayahs) {
        $("#p-start", md).textContent = ""; $("#p-end", md).textContent = ""; return;
      }
      const pv = await api("ayah_preview", { surah: +sel.value, first: +a.value, last: +b.value }).catch(() => null);
      if (pv) { $("#p-start", md).textContent = pv.start; $("#p-end", md).textContent = pv.end; }
    };
    sel.onchange = () => { a.value = 1; b.value = SURAHS[sel.value - 1].ayahs; update(); };
    a.oninput = b.oninput = update;
    r.parentElement.onclick = () => { rename = !rename; r.classList.toggle("on", rename); };
    update();
    $("[data-act=cancel]", md).onclick = () => (md.hidden = true);
    $("[data-act=ok]", md).onclick = () => attempt(async () => {
      await api("set_ayahs", { item_id: it.id, surah: +sel.value, first: +a.value, last: +b.value, rename });
      md.hidden = true;
      app.refresh();
    });
  }

  // ------------------------------------------------------------- making
  function renderMaking(m) {
    const run = S.run;
    const items = S.items.filter((i) => run.queue.includes(i.id));
    const cur = items.find((i) => i.id === run.item);
    const doneN = items.filter((i) => ["done", "skipped", "failed", "stopped"].includes(i.status)).length;
    if (!run.active) {
      const made = items.filter((i) => i.status === "done").length;
      const failed = items.filter((i) => i.status === "failed");
      const stopped = items.some((i) => i.status === "stopped");
      m.innerHTML = `<div class="head"><div><h1>${stopped ? "Stopped" : "All done"}</h1><p>${made} recording${made !== 1 ? "s" : ""} made${failed.length ? `, ${failed.length} didn't work` : ""}.</p></div></div>
        <div class="content"><div class="card" style="padding:28px;text-align:center;max-width:620px;margin:40px auto">
          <div style="font-size:44px;line-height:1">${stopped ? "⏹" : "✓"}</div>
          <div style="font-size:18px;font-weight:650;margin:10px 0 6px">${stopped ? "Stopped. Nothing half-made was left behind." : "Your videos are ready."}</div>
          ${failed.map((f) => `<div class="red" style="font-size:13px;margin-top:6px">${esc(f.name)}: ${esc(f.error)}</div>`).join("")}
          <div style="display:flex;gap:10px;justify-content:center;margin-top:18px">
            <button class="btn primary big" data-act="fin">See finished videos</button><button class="btn big" data-act="back">Make more</button></div></div></div>`;
      $("[data-act=fin]", m).onclick = () => go("finished");
      $("[data-act=back]", m).onclick = () => go("make");
      return;
    }
    const left = run.eta ? Math.max(1, Math.round(run.eta / 60)) : null;
    const steps = (run.steps || []).map((st) => {
      const mark = st.state === "done" ? "on" : st.state === "now" ? "now" : "";
      const extra = st.detail ? (/repeat/.test(st.detail) && !/no repeats/.test(st.detail) ? `<span class="chip good">${esc(st.detail)}</span>` : `<span class="muted">${esc(st.detail)}</span>`) : "";
      const bar = st.state === "now" && st.progress != null ? `<div class="prog" style="margin:9px 0 0 30px"><i style="width:${Math.round(st.progress * 100)}%"></i></div>` : "";
      return `<div><div class="steprow" style="${st.state === "todo" ? "color:var(--faint)" : ""}"><span class="check ${mark}"></span><div style="flex:1">${esc(st.label)}</div>${extra}</div>${bar}</div>`;
    }).join("");
    const pos = items.findIndex((i) => i.id === run.item) + 1;
    const frac = items.length ? (doneN + (curFrac(run))) / items.length : 0;
    m.innerHTML = `<div class="head"><div><h1>${run.paused ? "Paused" : "Making videos"}</h1>
      <p>Recording ${pos || doneN} of ${items.length}${left ? ` · about ${left} minute${left > 1 ? "s" : ""} left` : ""}</p></div>
      <div class="right"><button class="btn" data-act="pause">${run.paused ? "Carry on" : "Pause"}</button><button class="btn ghost danger" data-act="stop">Stop</button></div></div>
      <div class="content"><div class="prog" style="margin-bottom:20px"><i style="width:${Math.round(frac * 100)}%"></i></div>
      <div class="making">
        <div class="card" style="padding:20px 22px">
          ${cur ? `<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px"><div class="ficon ${cur.kind === "video" ? "v" : ""}">${ICON[cur.kind]}</div><div style="font-size:16px;font-weight:650">${esc(cur.name)}</div><span class="chip">${esc(cur.ref ? cur.ref.label : "")}</span></div>` : ""}
          <div class="stepslist">${steps || '<div class="muted">Getting started…</div>'}</div></div>
        <div>
          <div class="faint" style="font-size:12px;margin-bottom:8px">Right now on screen</div>
          <div class="slidebox" style="${run.slide ? `background-image:url(${run.slide})` : ""}"></div>
          <div class="faint" style="font-size:12px;margin:18px 0 8px">The list</div>
          <div style="display:flex;flex-direction:column;gap:8px">${items.map((i) => {
            const st = { done: '<span class="chip good">done</span>', working: '<span class="chip">working</span>', failed: '<span class="chip bad">didn\'t work</span>', skipped: '<span class="chip">already made</span>', stopped: '<span class="chip">stopped</span>' }[i.status] || '<span class="faint" style="font-size:12px">waiting</span>';
            return `<div class="steprow ${i.status === "queued" ? "muted" : ""}"><span class="check ${i.status === "done" ? "on" : i.status === "working" ? "now" : ""}"></span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(i.name)}</span><span class="right">${st}</span></div>`;
          }).join("")}</div>
          <div class="faint" style="font-size:12px;margin-top:18px">${S.settings.keep_awake ? "Your computer is staying awake until this is done." : ""}</div>
        </div></div></div>`;
    $("[data-act=pause]", m).onclick = () => api("pause", { on: !run.paused }).then(app.refresh);
    $("[data-act=stop]", m).onclick = () => api("stop").then(app.refresh);
  }
  function curFrac(run) {
    const st = run.steps || [];
    if (!st.length) return 0;
    let total = 0, done = 0;
    st.forEach((s) => { const c = Math.max(0.5, s.cost || 0); total += c; done += c * (s.state === "done" ? 1 : (s.progress || 0)); });
    return total ? done / total : 0;
  }

  // ------------------------------------------------------------- finished
  const revealWord = () => (S && S.platform === "darwin" ? "Show in Finder" : "Show in folder");
  async function renderFinished(m) {
    m.innerHTML = `<div class="head"><div><h1>Finished videos</h1><p class="muted">Loading…</p></div></div>`;
    const list = await api("projects");
    if (view !== "finished") return;
    const out = S ? S.settings.out_dir : "";
    if (!list.length) {
      m.innerHTML = `<div class="head"><div><h1>Finished videos</h1><p>Nothing yet. Videos you make show up here.</p></div></div>
        <div class="content"><div class="card" style="padding:30px;text-align:center;max-width:560px;margin:40px auto">
        <div class="muted">Add a recording on <b style="color:var(--ink)">Make videos</b> to get started.</div>
        <button class="btn primary" style="margin-top:14px" data-act="make">Make videos</button></div></div>`;
      $("[data-act=make]", m).onclick = () => go("make");
      return;
    }
    const nVideos = list.reduce((a, p) => a + Object.keys(p.outputs).length, 0);
    m.innerHTML = `<div class="head"><div><h1>Finished videos</h1><p>${list.length} recording${list.length > 1 ? "s" : ""} · ${nVideos} video${nVideos !== 1 ? "s" : ""} · saved to ${esc(out)}</p></div>
      <div class="right"><button class="btn" data-act="open">Open videos folder</button></div></div>
      <div class="content"><div class="rows">${list.map((p) => {
        const th = ["bg", "own", "black"].filter((k) => p.thumbs[k]).map((k) => `<div class="thumb" style="width:96px;height:54px;background-image:url(${p.thumbs[k]})"></div>`).join("");
        const first = p.outputs.bg || p.outputs.own || p.outputs.black;
        const st = p.doubts.length ? `<span class="chip warn">${p.doubts.length} thing${p.doubts.length > 1 ? "s" : ""} to check</span>` : `<span class="chip good">✓ Nothing looked doubtful</span>`;
        const ds = p.doubts.map((d) => `<div class="doubt"><button class="btn small" data-act="jump" data-id="${esc(p.id)}" data-t="${d.t}" style="font-variant-numeric:tabular-nums">▶ ${clock(d.t)}</button>
          <span>${esc(d.msg)}</span><button class="btn small ghost" style="margin-left:auto" data-act="fine" data-id="${esc(p.id)}" data-t="${d.t}">Looks fine</button></div>`).join("");
        return `<div class="card proj"><div class="top">${th || '<div class="thumb" style="width:96px;height:54px"></div>'}
          <div style="min-width:0"><div style="font-weight:650">${esc(p.name)}</div><div class="muted" style="font-size:12.5px">${esc(p.label)} · ${p.screens} screens${p.repeats ? ` · ${p.repeats} repeat${p.repeats > 1 ? "s" : ""}` : ""}</div></div>
          <div style="margin-left:auto;display:flex;gap:8px;align-items:center">${st}
          ${[["bg", "Background"], ["own", "Your video"], ["black", "Black"]].filter(([k]) => p.outputs[k]).map(([k, label]) =>
            `<button class="btn small" data-act="play" data-p="${esc(p.outputs[k])}" title="Play the ${label.toLowerCase()} one">▶ ${label}</button>`).join("")}
          <button class="btn small" data-act="edit" data-id="${esc(p.id)}">Edit screens</button>
          ${first ? `<button class="btn small ghost" data-act="reveal" data-p="${esc(first)}">${revealWord()}</button>` : ""}</div></div>${ds}</div>`;
      }).join("")}</div></div>`;
    $("[data-act=open]", m).onclick = () => api("open_output");
    $$("[data-act=play]", m).forEach((b) => b.onclick = () => api("open_file", { path: b.dataset.p }));
    $$("[data-act=reveal]", m).forEach((b) => b.onclick = () => api("reveal", { path: b.dataset.p }));
    $$("[data-act=edit]", m).forEach((b) => b.onclick = () => openEditor(b.dataset.id));
    $$("[data-act=jump]", m).forEach((b) => b.onclick = () => openEditor(b.dataset.id, +b.dataset.t));
    $$("[data-act=fine]", m).forEach((b) => b.onclick = () => api("dismiss", { pid: b.dataset.id, t: +b.dataset.t }).then(() => renderFinished(m)));
  }

  // ------------------------------------------------------------- editor
  let E = null;      // the recording being edited
  async function openEditor(pid, at) {
    const p = await attempt(() => api("project", { pid }));
    if (!p) return;
    const kinds = ["bg", "own", "black"].filter((k) => p.videos[k]);
    E = { p, parts: p.parts.map((x) => ({ ...x })), orig: JSON.stringify(p.parts.map(stripPart)),
          sel: 0, kind: kinds[0] || "black", kinds, editing: -1, at: at || 0, pics: {} };
    if (at != null) E.sel = Math.max(0, E.parts.findIndex((x) => x.start <= at && at < x.end));
    go("editor");
  }
  function stripPart(x) {
    return { start: x.start, arabic: x.arabic, english: x.english };
  }
  function settle() {
    E.parts.sort((a, b) => a.start - b.start);
    E.parts[0].start = 0;
    E.parts.forEach((x, i) => { x.end = i + 1 < E.parts.length ? E.parts[i + 1].start : E.p.duration; });
    let maxHi = -1;
    E.parts.forEach((x, i) => { x.repeat = x.lo != null && i > 0 && x.lo <= maxHi; if (x.hi != null) maxHi = Math.max(maxHi, x.hi); });
  }
  function changed(x) {
    const o = JSON.parse(E.orig);
    return !o.some((y) => y.start === x.start && y.arabic === x.arabic && y.english === x.english);
  }
  const dirty = () => JSON.stringify(E.parts.map(stripPart)) !== E.orig;

  function renderEditor(m) {
    if (!E) return go("finished");
    settle();
    const p = E.p, dur = p.duration;
    const blocks = E.parts.map((x, i) => `<i data-i="${i}" class="${i === E.sel ? "sel" : x.repeat ? "rep" : ""}" style="left:${(x.start / dur) * 100}%;width:calc(${((x.end - x.start) / dur) * 100}% - 2px)" title="${clock(x.start, 1)}"></i>`).join("");
    const wave = (p.wave || []).map((v) => `<b style="height:${Math.max(4, v * 100)}%"></b>`).join("");
    const rows = E.parts.map((x, i) => {
      const sel = i === E.sel;
      const ed = E.editing === i;
      const canSplit = x.lo != null && !x.custom && x.hi > x.lo;
      const body = ed
        ? `<textarea class="ar" rows="2" data-f="arabic">${esc(x.arabic)}</textarea><textarea rows="2" data-f="english" style="margin-top:6px">${esc(x.english)}</textarea>
           <div class="tools"><button class="btn small primary" data-act="done-edit">Done</button></div>`
        : `<div class="ar arline">${esc(x.arabic)}</div><div class="enline">${esc(x.english) || '<span class="faint">(no English)</span>'}</div>
           ${sel ? `<div class="tools"><button class="btn small" data-act="nudge" data-d="-0.1" ${i === 0 ? "disabled" : ""}>◀ 0.1s</button><button class="btn small" data-act="nudge" data-d="0.1" ${i === 0 ? "disabled" : ""}>0.1s ▶</button>
           <button class="btn small" data-act="split" ${canSplit ? "" : "disabled"} title="Split this screen in two">✂ Split</button><button class="btn small" data-act="join" ${i + 1 < E.parts.length ? "" : "disabled"} title="Join this screen with the next one">Join next</button>
           <button class="btn small" data-act="edit" title="Change the words">✎ Edit</button></div>` : ""}`;
      return `<div class="scr ${sel ? "sel" : ""} ${changed(x) ? "changed" : ""}" data-i="${i}">
        <div><div class="time">${clock(x.start, 1)}</div><div class="faint" style="font-size:11px">ayah ${x.ayah}</div>${x.repeat ? '<span class="chip blue" style="height:20px;font-size:11px;margin-top:4px">repeat</span>' : ""}</div>
        <div style="min-width:0">${body}</div></div>`;
    }).join("");
    const doubts = (p.doubts || []).map((d) => `<button class="btn small" data-act="seek" data-t="${d.t}" title="${esc(d.msg)}">⚠ ${clock(d.t)}</button>`).join("");
    const curChanged = changed(E.parts[E.sel]);
    const kindName = { bg: "With background", own: "Your video", black: "Black" };
    m.innerHTML = `<div class="head" style="padding-bottom:10px"><div><h1>${esc(p.name)}</h1><p>Click a screen to jump to it. Change anything, then remake.</p></div>
      <div class="right">${E.kinds.length > 1 ? `<div class="card" style="display:flex;padding:3px;border-radius:9px">${E.kinds.map((k) => `<button class="btn small ${k === E.kind ? "" : "ghost"}" style="border:0" data-act="kind" data-k="${k}">${kindName[k]}</button>`).join("")}</div>` : ""}
      <button class="btn ghost" data-act="back">← Back</button></div></div>
      <div class="content" style="overflow:hidden"><div class="editor">
        <div style="display:flex;flex-direction:column;min-width:0">
          <div class="player">${curChanged
            ? `<img id="pic" alt=""><span class="chip warn note">The new look of this screen — press Save and remake to make the video</span>`
            : (p.videos[E.kind] ? `<video id="vid" src="${p.videos[E.kind]}" controls preload="auto" playsinline></video>` : `<div style="aspect-ratio:16/9;display:flex;align-items:center;justify-content:center" class="muted">The video file was moved or deleted.</div>`)}</div>
          <div class="timeline" id="tl">${blocks}</div>
          <div class="wave" id="wave">${wave}<div class="playhead" id="ph" style="left:0"></div></div>
          <div class="faint" style="display:flex;justify-content:space-between;font-size:11.5px;margin-top:4px"><span>0:00</span><span>each block = one screen · click to jump there${doubts ? "" : ""}</span><span>${clock(dur)}</span></div>
          ${doubts ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px;align-items:center"><span class="faint" style="font-size:12px">To check:</span>${doubts}</div>` : ""}
        </div>
        <div class="screens" id="screens">${rows}</div>
      </div></div>
      <div class="bar"><button class="btn" data-act="redo">Redo from scratch</button><span class="faint" style="font-size:12.5px">listens again and forgets your changes</span>
        <span style="margin-left:auto" class="${dirty() ? "chip warn" : (p.doubts && p.doubts.length ? "chip warn" : "chip good")}">${dirty() ? "Changes not saved yet" : (p.doubts && p.doubts.length ? `${p.doubts.length} thing${p.doubts.length > 1 ? "s" : ""} to check` : "✓ Nothing looked doubtful")}</span>
        <button class="btn primary big" data-act="save" ${dirty() ? "" : "disabled"}>Save and remake videos</button></div>`;

    const vid = $("#vid", m);
    const ph = $("#ph", m);
    const seek = (t) => { E.at = t; if (vid) vid.currentTime = t; ph.style.left = (t / dur) * 100 + "%"; };
    if (vid) {
      vid.addEventListener("loadedmetadata", () => { vid.currentTime = E.at || E.parts[E.sel].start; });
      vid.addEventListener("timeupdate", () => {
        ph.style.left = (vid.currentTime / dur) * 100 + "%";
        E.at = vid.currentTime;
        const i = E.parts.findIndex((x) => x.start <= vid.currentTime && vid.currentTime < x.end);
        if (i >= 0 && i !== E.sel && !vid.paused) { E.sel = i; highlight(m); }
      });
    }
    ph.style.left = ((E.at || 0) / dur) * 100 + "%";
    if (curChanged) {
      const x = E.parts[E.sel];
      const key = E.kind + "|" + x.arabic + "|" + x.english;
      const show = (src) => { const img = $("#pic", m); if (img) img.src = src; };
      const pics = E.pics;
      if (pics[key]) show(pics[key]);
      else api("screen_picture", { pid: p.id, arabic: x.arabic, english: x.english, kind: E.kind }).then((src) => { pics[key] = src; show(src); }).catch(() => {});
    }
    const pickAt = (el, ev) => (ev.clientX - el.getBoundingClientRect().left) / el.getBoundingClientRect().width * dur;
    $("#tl", m).onclick = (ev) => { const i = ev.target.dataset.i; if (i != null) { select(+i); } else seek(pickAt($("#tl", m), ev)); };
    $("#wave", m).onclick = (ev) => { const t = pickAt($("#wave", m), ev); seek(t); const i = E.parts.findIndex((x) => x.start <= t && t < x.end); if (i >= 0 && i !== E.sel) { E.sel = i; E.at = t; renderEditor(m); } };
    $$(".scr", m).forEach((r) => r.onclick = (ev) => { if (ev.target.closest("button,textarea")) return; select(+r.dataset.i); });
    $$("[data-act=nudge]", m).forEach((b) => b.onclick = () => {
      const i = E.sel, x = E.parts[i];
      const lo = E.parts[i - 1].start + 0.3, hi = (E.parts[i + 1] ? E.parts[i + 1].start : dur) - 0.3;
      x.start = Math.round(Math.min(hi, Math.max(lo, x.start + +b.dataset.d)) * 100) / 100;
      E.at = x.start; renderEditor(m);
    });
    $$("[data-act=split]", m).forEach((b) => b.onclick = () => splitDialog(E.sel));
    $$("[data-act=join]", m).forEach((b) => b.onclick = () => attempt(async () => {
      const a = E.parts[E.sel], c = E.parts[E.sel + 1];
      // a repeat, or words you typed: keep both, one after the other
      let merged = { start: a.start, ayah: c.ayah, arabic: a.arabic + " " + c.arabic, english: (a.english + " " + c.english).trim(), custom: true };
      if (a.lo != null && c.lo != null && !a.custom && !c.custom && c.lo === a.hi + 1) {
        const r = await api("words", { pid: p.id, lo: a.lo, hi: c.hi });
        merged = { start: a.start, ayah: r.ayah, lo: a.lo, hi: c.hi, arabic: r.arabic, english: r.english, times: (a.times || []).concat(c.times || []) };
      }
      E.parts.splice(E.sel, 2, merged);
      renderEditor(m);
    }));
    $$("[data-act=edit]", m).forEach((b) => b.onclick = () => { E.editing = E.sel; renderEditor(m); });
    $$("[data-act=done-edit]", m).forEach((b) => b.onclick = () => {
      const r = b.closest(".scr"), x = E.parts[+r.dataset.i];
      const ar = $("[data-f=arabic]", r).value.trim(), en = $("[data-f=english]", r).value.trim();
      if (ar !== x.arabic || en !== x.english) { x.arabic = ar; x.english = en; x.custom = true; }
      E.editing = -1; renderEditor(m);
    });
    $$("[data-act=seek]", m).forEach((b) => b.onclick = () => { const t = +b.dataset.t; E.sel = Math.max(0, E.parts.findIndex((x) => x.start <= t && t < x.end)); E.at = t; renderEditor(m); });
    $$("[data-act=kind]", m).forEach((b) => b.onclick = () => { E.kind = b.dataset.k; renderEditor(m); });
    $("[data-act=back]", m).onclick = () => { if (!dirty() || confirmLeave()) go("finished"); };
    $("[data-act=redo]", m).onclick = () => confirmDialog("Redo from scratch?", "It listens to the recording again and works out every screen fresh. Any changes you made here are lost.", "Redo it", async () => {
      await attempt(() => api("redo", { pid: p.id })); go("making");
    });
    $("[data-act=save]", m).onclick = () => attempt(async () => {
      await api("save_screens", { pid: p.id, parts: E.parts });
      await api("remake", { pid: p.id });
      E = null;
      go("making");
    });
    const sel = $(".scr.sel", m);
    if (sel) sel.scrollIntoView({ block: "nearest" });

    function select(i) {
      E.sel = i; E.editing = -1; E.at = E.parts[i].start;
      if (vid && !changed(E.parts[i])) { vid.currentTime = E.at; highlight(m); return; }
      renderEditor(m);
    }
  }
  function highlight(m) {
    // only move the highlight, without rebuilding the player
    const prevChanged = $("#pic", m) != null;
    if (prevChanged || changed(E.parts[E.sel])) return renderEditor(m);
    $$(".scr", m).forEach((r) => r.classList.toggle("sel", +r.dataset.i === E.sel));
    $$("#tl i", m).forEach((b) => { const i = +b.dataset.i; b.className = i === E.sel ? "sel" : E.parts[i].repeat ? "rep" : ""; });
    // the tools row lives only on the selected screen, so redraw the list part
    const keep = $("#vid", m);
    const t = keep ? keep.currentTime : 0;
    const playing = keep && !keep.paused;
    if (!playing) { renderEditor(m); const v = $("#vid", m); if (v) v.currentTime = t; }
    else { const s = $(".scr.sel", m); if (s) s.scrollIntoView({ block: "nearest" }); }
  }
  function confirmLeave() {
    return window.confirm("You have changes that aren't saved. Leave without saving?");
  }

  async function splitDialog(i) {
    const x = E.parts[i];
    const tokens = x.arabic.split(/\s+/);
    // words that count (ayah numbers stay glued to the word before them)
    const words = [];
    tokens.forEach((t) => { if (isNumberToken(t) && words.length) words[words.length - 1] += " " + t; else words.push(t); });
    let at = Math.max(1, Math.floor(words.length / 2));
    const md = $("#modal");
    md.hidden = false;
    const draw = async () => {
      const chips = words.map((w, k) => (k ? `<span class="gap ${k === at ? "on" : ""}" data-k="${k}"></span>` : "") + `<span class="w ${k >= at ? "b" : ""}">${esc(w)}</span>`).join("");
      md.innerHTML = `<div class="dialog" style="width:820px">
        <h2>Split this screen in two</h2>
        <div class="muted" style="margin:4px 0 18px">Click between two words. The new screen starts when you said that word — no need to type a time.</div>
        <div class="wordchips">${chips}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px" id="sp-prev"><div class="faint">Working it out…</div></div>
        <div class="faint" style="font-size:12.5px;margin-top:12px">The English splits on its own, the same way it does for every video.</div>
        <div class="actions"><button class="btn" data-act="cancel">Cancel</button><button class="btn primary" data-act="ok" disabled>Split</button></div></div>`;
      $$(".gap", md).forEach((g) => g.onclick = () => { at = +g.dataset.k; draw(); });
      $("[data-act=cancel]", md).onclick = () => (md.hidden = true);
      const res = await api("split_parts", { pid: E.p.id, part: x, at }).catch((e) => { toast(e.message, true); return null; });
      if (!res) return;
      const [a, b] = res;
      $("#sp-prev", md).innerHTML = [a, b].map((y, k) => `<div class="card" style="padding:12px 14px;${k ? "background:rgba(120,160,255,.08);border-color:rgba(120,160,255,.3)" : "background:rgba(63,174,140,.08);border-color:rgba(63,174,140,.3)"}">
        <div class="faint" style="font-size:12px">Screen ${k + 1} · starts ${clock(y.start, 1)}</div><div class="ar" style="font-size:20px">${esc(y.arabic)}</div><div style="font-size:13px">${esc(y.english)}</div></div>`).join("");
      const ok = $("[data-act=ok]", md);
      ok.disabled = false;
      ok.onclick = () => { E.parts.splice(i, 1, a, b); md.hidden = true; renderEditor($("#main")); };
    };
    draw();
  }

  function confirmDialog(title, text, okLabel, onOk) {
    const md = $("#modal");
    md.hidden = false;
    md.innerHTML = `<div class="dialog"><h2>${esc(title)}</h2><p class="muted">${esc(text)}</p>
      <div class="actions"><button class="btn" data-act="cancel">Cancel</button><button class="btn primary" data-act="ok">${esc(okLabel)}</button></div></div>`;
    $("[data-act=cancel]", md).onclick = () => (md.hidden = true);
    $("[data-act=ok]", md).onclick = () => { md.hidden = true; onOk(); };
  }

  // ------------------------------------------------------------- settings
  let previewTimer = null;
  function renderSettings(m) {
    const s = S.settings;
    const slider = (key, min, max, step, fmt) => `<div class="slider"><input type="range" data-k="${key}" min="${min}" max="${max}" step="${step}" value="${s[key]}"><span data-v="${key}">${fmt(s[key])}</span></div>`;
    const where = (v) => (v < 0.44 ? "higher" : v > 0.5 ? "lower" : "middle");
    const fm = { arabic_size: (v) => v, english_size: (v) => v, fade: (v) => (+v).toFixed(2) + "s", bg_blur: (v) => v, text_position: where };
    m.innerHTML = `<div class="head"><div><h1>Settings</h1><p>Saved on this computer, used for every video until you change them.</p></div></div>
      <div class="content"><div class="settings"><div>
        <div class="card" style="padding:18px 20px;margin-bottom:16px">
          <div style="font-weight:650;margin-bottom:12px">Background for MP3s</div>
          <div style="display:flex;gap:16px;align-items:center">
            <div class="thumb" style="width:200px;height:112px;${s.bg_url ? `background-image:url(${s.bg_url})` : "border:1px dashed #445;display:flex;align-items:center;justify-content:center"}">${s.bg_url ? "" : '<span class="faint" style="font-size:12px">none yet</span>'}</div>
            <div style="flex:1"><div style="font-weight:600">${s.bg_name ? esc(s.bg_name) : "No background yet"}</div>
              <div class="faint" style="font-size:12.5px;margin:2px 0 12px">Used behind every MP3 you tick “With background” for. A short clip plays forwards then backwards, so you never see a jump. Videos you add (MP4) use themselves instead.</div>
              <div style="display:flex;gap:8px"><button class="btn small" data-act="bg">${s.bg_name ? "Change video…" : "Choose a video…"}</button>${s.bg_name ? '<button class="btn small ghost" data-act="nobg">Remove</button>' : ""}</div></div>
          </div>
          <div class="srow" style="margin-top:8px;border-top:1px solid var(--line)"><div class="grow"><div style="font-weight:600">Blur the background</div><div class="sub">Leave at 0 if your clip is already blurred.</div></div>${slider("bg_blur", 0, 30, 1, fm.bg_blur)}</div>
        </div>
        <div class="card" style="padding:4px 20px">
          <div class="srow"><div class="grow"><div style="font-weight:600">Save videos to</div><div class="sub">${esc(s.out_dir)}</div></div><button class="btn small" data-act="out">Change…</button></div>
          <div class="srow"><div class="grow"><div style="font-weight:600">Skip ones already made</div><div class="sub">Also counts videos you moved into a “Published” folder inside it.</div></div><button class="toggle ${s.skip_done ? "on" : ""}" data-t="skip_done"></button></div>
          <div class="srow"><div class="grow"><div style="font-weight:600">Keep the computer awake while making videos</div><div class="sub">So a video never gets cut off halfway.</div></div><button class="toggle ${s.keep_awake ? "on" : ""}" data-t="keep_awake"></button></div>
          <div class="srow"><div class="grow"><div style="font-weight:600">English translation</div><div class="sub">The Clear Quran — Dr. Mustafa Khattab</div></div><span class="chip">built in</span></div>
        </div>
        <div class="faint" style="font-size:12px;margin-top:16px">Quran Video Maker ${esc(S.version)} · made by <a href="#" data-act="tt" style="color:var(--accent)">@zizorecites</a> — check it out on TikTok</div>
      </div><div>
        <div class="faint" style="font-size:12px;margin-bottom:8px">Live preview</div>
        <div class="slidebox" id="pv" style="aspect-ratio:16/9"></div>
        <div style="margin-top:14px;display:flex;flex-direction:column;gap:12px">
          <div style="display:flex;justify-content:space-between;align-items:center"><span class="muted">Arabic size</span>${slider("arabic_size", 70, 170, 1, fm.arabic_size)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center"><span class="muted">English size</span>${slider("english_size", 30, 90, 1, fm.english_size)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center"><span class="muted">Text position<br><span class="faint" style="font-size:11.5px">up or down the screen</span></span>${slider("text_position", 0.2, 0.8, 0.01, fm.text_position)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center"><span class="muted">Fade between screens</span>${slider("fade", 0, 1, 0.05, fm.fade)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center"><span class="muted">Video size</span><span class="chip">1920 × 1080 · 30 fps</span></div>
          <div class="faint" style="font-size:12px">Videos you add (MP4) keep their own shape.</div>
          <button class="btn small ghost" data-act="reset" style="align-self:flex-start;padding:0">Reset text to how it started</button>
        </div></div></div></div>`;
    const pv = $("#pv", m);
    const look = () => ({ arabic_size: +$("[data-k=arabic_size]", m).value, english_size: +$("[data-k=english_size]", m).value, fade: +$("[data-k=fade]", m).value, text_position: +$("[data-k=text_position]", m).value });
    const updatePreview = () => { clearTimeout(previewTimer); previewTimer = setTimeout(() => api("style_preview", { look: look() }).then((src) => (pv.style.backgroundImage = `url(${src})`)), 120); };
    updatePreview();
    $$("input[type=range]", m).forEach((r) => {
      r.oninput = () => { $(`[data-v=${r.dataset.k}]`, m).textContent = fm[r.dataset.k](r.value); if (r.dataset.k !== "bg_blur") updatePreview(); };
      r.onchange = () => api("settings_set", { changes: { [r.dataset.k]: +r.value } }).then(refresh);
    });
    $$("[data-t]", m).forEach((t) => t.onclick = () => api("settings_set", { changes: { [t.dataset.t]: !S.settings[t.dataset.t] } }).then(async () => { await refresh(); renderSettings(m); }));
    $("[data-act=bg]", m).onclick = () => attempt(() => api("choose_background")).then(async () => { await refresh(); renderSettings(m); });
    const nb = $("[data-act=nobg]", m);
    if (nb) nb.onclick = () => api("remove_background").then(async () => { await refresh(); renderSettings(m); });
    $("[data-act=out]", m).onclick = () => attempt(() => api("choose_output")).then(async () => { await refresh(); renderSettings(m); });
    $("[data-act=reset]", m).onclick = () => api("settings_set", { changes: { arabic_size: 118, english_size: 56, fade: 0.25, text_position: 0.47 } }).then(async () => { await refresh(); renderSettings(m); });
    $("[data-act=tt]", m).onclick = (e) => { e.preventDefault(); api("open_tiktok"); };
  }

  // ------------------------------------------------------------- wiring
  $$(".nav").forEach((n) => n.onclick = () => {
    if (S && !S.setup.ready && !setupSkipped) return;
    if (view === "editor" && E && dirty() && !confirmLeave()) return;
    let v = n.dataset.view;
    if (v === "make" && S && S.run.active) v = "making";
    go(v);
  });
  $("#credit").onclick = (e) => { e.preventDefault(); api("open_tiktok"); };

  // drag and drop: the app window passes the real file paths to the backend
  document.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; document.body.classList.add("dragging"); const d = $("#drop"); if (d) d.classList.add("over"); });
  document.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) { document.body.classList.remove("dragging"); const d = $("#drop"); if (d) d.classList.remove("over"); } });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove("dragging");
    const d = $("#drop"); if (d) d.classList.remove("over");
    if (view !== "make" && view !== "making") go("make");
    setTimeout(app.refresh, 400);
    setTimeout(app.refresh, 1500);
    if (!window.pywebview) toast("Drag and drop works in the app. Here, use Choose files.");
  });

  refresh();
  setInterval(() => { if (view !== "editor" && view !== "settings" && view !== "finished") refresh(); else if (S && S.run.active) refresh(); }, 800);
})();
