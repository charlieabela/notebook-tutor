/* Notebook Tutor, standalone host.
 *
 * The tutor's page was first written for a Claude artifact and for VS Code; this file is the third host.
 * It gives the page:
 *   window.NBT_HOST  notebook files, a Jupyter kernel and settings, through the local server (/api/...);
 *   window.claude    the small part of the artifact API the page uses: use("sample") for the language model.
 * The server holds the student's API key. This page never receives it.
 */
(function () {
  "use strict";
  const BOOT = window.NT_BOOT || {};
  const TOKEN = BOOT.token;
  let prefs = Object.assign({}, BOOT.prefs || {});
  let current = null;
  const running = { count: 0, stops: 0 };   // cells waiting for Python, and Stop presses                 // path of the open notebook, relative to the tutor's folder
  let nbKnownResolve;
  const nbKnown = new Promise((r) => (nbKnownResolve = r));

  // ------------------------------------------------------------------ server calls
  async function api(method, path, body, opts = {}) {
    const headers = { "X-NT-Token": TOKEN };
    let data;
    if (body instanceof Blob || body instanceof ArrayBuffer) data = body;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; data = JSON.stringify(body); }
    let res;
    try { res = await fetch("/api/" + path, { method, headers, body: data, signal: opts.signal }); }
    catch (e) {
      if (e && e.name === "AbortError") throw { code: "cancelled" };
      throw Object.assign(new Error("The tutor's server is not running. Start it again with `nt`."), { code: "server_down" });
    }
    let out = {};
    try { out = await res.json(); } catch {}
    if (!res.ok) {
      const err = (out && out.error) || {};
      throw Object.assign(new Error(err.message || `Request failed (${res.status})`), { code: err.code || "http_" + res.status });
    }
    return out;
  }
  const q = (o) => Object.entries(o).map(([k, v]) => k + "=" + encodeURIComponent(v == null ? "" : v)).join("&");
  const modeKey = () => "mode:" + BOOT.root + "|" + current;
  const dirOf = (p) => (p && p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "");
  const baseName = (p) => (p || "").split("/").pop();
  const escH = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const page = (name) => (typeof window[name] === "function" ? window[name] : () => {});

  // ------------------------------------------------------------------ preferences (kept by the server, so they survive a new port)
  let prefTimer = 0;
  function savePrefs() { clearTimeout(prefTimer); prefTimer = setTimeout(() => api("PUT", "prefs", prefs).catch(() => {}), 400); }
  const store = {
    get(k) { return prefs[k]; },
    set(k, v) { if (v === null || v === undefined) delete prefs[k]; else prefs[k] = v; savePrefs(); },
  };

  // ------------------------------------------------------------------ styles for the host's dialogs
  const css = document.createElement("style");
  css.textContent = `
  dialog.nt { max-width: 44rem; width: calc(100% - 32px); }
  dialog.nt .db { display: grid; gap: 12px; }
  dialog.nt label.f { display: grid; gap: 4px; font-weight: 600; }
  dialog.nt label.f span.h, dialog.nt .h { font-weight: 400; font-size: 12.5px; opacity: .8; line-height: 1.45; }
  dialog.nt input[type=text], dialog.nt input[type=password], dialog.nt select { font: inherit; padding: 7px 9px; border: 1px solid #c9c9c9; border-radius: 8px; background: transparent; color: inherit; }
  dialog.nt .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  dialog.nt .res { font-size: 13px; padding: 8px 10px; border-radius: 8px; background: rgba(127,127,127,.12); white-space: pre-wrap; }
  dialog.nt .res.ok { background: rgba(40,160,90,.14); } dialog.nt .res.bad { background: rgba(200,60,60,.14); }
  dialog.nt ul.nbs { list-style: none; margin: 0; padding: 0; max-height: 46vh; overflow: auto; border: 1px solid rgba(127,127,127,.3); border-radius: 10px; }
  dialog.nt ul.nbs li { display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 9px 12px; border-bottom: 1px solid rgba(127,127,127,.18); cursor: pointer; }
  dialog.nt ul.nbs li:last-child { border-bottom: 0; }
  dialog.nt ul.nbs li:hover, dialog.nt ul.nbs li:focus { background: rgba(127,127,127,.1); outline: none; }
  dialog.nt ul.nbs small { opacity: .7; white-space: nowrap; }
  dialog.nt code { font-size: 12px; word-break: break-all; }
  dialog.nt.ref { max-width: 60rem; }
  dialog.nt .ref h1 { font-size: 1.35rem; margin: 6px 0 4px; } dialog.nt .ref h2 { font-size: 1.1rem; margin: 18px 0 6px; }
  dialog.nt .ref h3 { font-size: .98rem; margin: 14px 0 4px; }
  dialog.nt .ref table { border-collapse: collapse; width: 100%; font-size: 12.5px; margin: 6px 0 10px; }
  dialog.nt .ref th, dialog.nt .ref td { border: 1px solid rgba(127,127,127,.3); padding: 5px 7px; text-align: left; vertical-align: top; }
  dialog.nt .ref li { margin: 4px 0; } dialog.nt .ref code { word-break: normal; }
  dialog.nt .ref pre code { white-space: pre; }`;
  document.head.append(css);

  function dialog(id, title) {
    let d = document.getElementById(id);
    if (d) d.remove();
    d = document.createElement("dialog");
    d.id = id; d.className = "nt";
    d.innerHTML = `<div class="dh"><h3>${escH(title)}</h3><button class="btn ghost" type="button" data-close>Close</button></div><div class="db"></div>`;
    d.querySelector("[data-close]").onclick = () => d.close();
    document.body.append(d);
    return { d, body: d.querySelector(".db") };
  }

  // ------------------------------------------------------------------ the topic reference
  // One page per topic, generated by the tutor's own kit: what the topic covers, what learners do themselves, what
  // the kit does for them, and every helper of T = kit.tools() with what it does. Links between topics stay inside
  // the dialog.
  let current_topic = null, current_kit_note = null;
  async function reference(name) {
    const { d, body } = dialog("ntRef", "Topic reference");
    d.classList.add("ref");
    body.innerHTML = `<div class="res">Preparing the reference…</div>`;
    if (!d.open) d.showModal();
    await showReference(body, name || current_topic || "");
  }
  async function showReference(body, name) {
    let r;
    try { r = await api("GET", "kit/reference?" + q({ topic: name })); }
    catch (e) { body.innerHTML = `<div class="res bad">${escH(e.message)}</div>`; return; }
    if (!r.markdown) { body.innerHTML = `<div class="res">${escH(r.note)}</div>`; return; }
    const options = [`<option value="README">All topics</option>`].concat(r.topics.map((t) => `<option value="${escH(t.name)}">${escH(t.title)}</option>`));
    const note = current_kit_note && name && name === current_topic ? `<div class="res">${escH(current_kit_note)}</div>` : "";
    body.innerHTML = `<div class="row"><select data-topic aria-label="Topic">${options.join("")}</select>` +
      `<span class="h">From ai-learning-kit ${escH(r.kit)}. <code>kit.source(T.name)</code> in a cell shows a helper's code.</span></div>${note}<div class="prose ref"></div>`;
    const select = body.querySelector("[data-topic]");
    select.value = r.name;
    select.onchange = () => showReference(body, select.value);
    const prose = body.querySelector(".ref");
    const text = r.markdown.replace(/^\*Generated from the kit by[^\n]*\*\s*$/m, "");   // a note for the kit's authors
    prose.innerHTML = page("mdToHtml")(text);
    prose.querySelectorAll('a[href$=".md"]').forEach((a) => {
      const target = a.getAttribute("href").replace(/\.md$/, "");
      a.removeAttribute("target"); a.href = "#" + target;
      a.onclick = (e) => { e.preventDefault(); showReference(body, target); };
    });
    body.scrollTop = 0;
  }

  // ------------------------------------------------------------------ opening notebooks
  const SHOWN = 5;                                   // the Open dialog lists the five most recent notebooks
  const recentKey = () => "recent:" + BOOT.root;
  const recent = () => (Array.isArray(prefs[recentKey()]) ? prefs[recentKey()] : []);
  function byRecent(list) {   // most recently opened first, then most recently changed
    const order = new Map(recent().map((p, i) => [p, i]));
    return list.slice().sort((a, b) => (order.has(a.path) ? order.get(a.path) : 1e9) - (order.has(b.path) ? order.get(b.path) : 1e9) || b.modified - a.modified);
  }
  function fmtTime(t) { try { return new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); } catch { return ""; } }

  async function openPath(path) {
    const nb = await api("GET", "notebook?" + q({ path }));
    let kit = {};
    try { kit = await api("GET", "kit/context?" + q({ path })); } catch {}
    current = nb.path;
    prefs["last:" + BOOT.root] = current;
    prefs[recentKey()] = [current, ...recent().filter((p) => p !== current)].slice(0, 100);
    savePrefs();
    nbKnownResolve();
    document.title = baseName(current).replace(/\.ipynb$/i, "") + " · Notebook Tutor";
    const ctx = kit.context || null;
    const meta = kit.notebook_meta || {};
    current_topic = (ctx && ctx.topic) || meta.topic || null;
    current_kit_note = kit.notebook_kit ? `This notebook was written for ai-learning-kit ${kit.notebook_kit}, and the tutor runs it on that version. The reference describes the topics of the tutor's own kit, so some names may differ from the ones this notebook uses.` : null;
    const level = meta.level || (ctx && ctx.level) || null;   // the notebook's own level, else the topic's
    const notices = [];
    if (kit.version_note) notices.push(escH(kit.version_note));
    if (kit.context_error) notices.push("The tutor could not read this notebook's ai-learning-kit topic: " + escH(kit.context_error));
    window.NBT_HOST.onInit({
      text: nb.text, fileName: nb.name,
      mode: prefs[modeKey()] || null,
      level, levelForce: !!level,
      kit: ctx,
      notice: notices.length ? "<b>Note.</b> " + notices.join(" ") : null,
    });
    refreshFiles();
  }

  async function refreshFiles() {
    if (!current) return;
    try { const r = await api("GET", "files?" + q({ folder: dirOf(current) || "." })); window.NBT_HOST.onFiles(r.files); } catch {}
  }

  async function copySamples() {
    const samples = [["nb-guided", "samples/guided_linear_regression.ipynb"], ["nb-practice", "samples/practice_rents.ipynb"]];
    for (const [id, path] of samples) {
      const node = document.getElementById(id);
      if (node) await api("PUT", "notebook?" + q({ path }), { text: node.textContent });
    }
    return samples[0][1];
  }

  async function openDialog(opts = {}) {
    const { d, body } = dialog("ntOpen", "Open a notebook");
    body.innerHTML = `<p class="h">Add the notebook your lecturer gives you with <b>Add a notebook</b>. The tutor keeps your copy, with your work, in <code>${escH(BOOT.root)}</code>, so next time you open it from this list.</p><div class="res">Looking for notebooks…</div>`;
    if (!d.open) d.showModal();
    if (opts.firstRun) { d.querySelector("[data-close]").hidden = true; d.addEventListener("cancel", (e) => { if (!current) e.preventDefault(); }); }
    let list = [];
    try { list = (await api("GET", "notebooks")).notebooks; } catch (e) { body.querySelector(".res").textContent = e.message; return; }
    const res = body.querySelector(".res");
    if (!list.length) {
      res.innerHTML = "You have not added a notebook yet.";
    } else {
      res.remove();
      list = byRecent(list);
      const ul = document.createElement("ul"); ul.className = "nbs";
      list.forEach((n, i) => {
        const li = document.createElement("li"); li.tabIndex = 0; li.hidden = i >= SHOWN;
        li.innerHTML = `<span><b>${escH(n.name)}</b>${n.folder ? `<br><small>${escH(n.folder)}</small>` : ""}</span><small>${escH(fmtTime(n.modified))}</small>`;
        const go = async () => { d.close(); try { await openPath(n.path); } catch (e) { page("showNotice")(`<b>Couldn't open ${escH(n.name)}.</b> ${escH(e.message)}`); } };
        li.onclick = go; li.onkeydown = (e) => { if (e.key === "Enter") go(); };
        ul.append(li);
      });
      body.append(ul);
      if (list.length > SHOWN) {
        const more = document.createElement("button"); more.type = "button"; more.className = "btn ghost";
        more.textContent = `Show all ${list.length} notebooks`;
        more.onclick = () => { ul.querySelectorAll("li").forEach((li) => (li.hidden = false)); more.remove(); };
        body.append(more);
      }
    }
    if (BOOT.legacy) {
      const p = document.createElement("p"); p.className = "h";
      p.innerHTML = `Notebooks you used with an earlier version of the tutor are in <code>${escH(BOOT.legacy)}</code>. Add the ones you still need with <b>Add a notebook</b>; your work in them comes along.`;
      body.append(p);
    }
    const row = document.createElement("div"); row.className = "row";
    row.innerHTML = `<button class="btn primary" type="button" data-add>Add a notebook from this computer…</button><button class="btn" type="button" data-samples>Copy the two sample notebooks here</button><input type="file" accept=".ipynb" hidden>`;
    const input = row.querySelector("input");
    row.querySelector("[data-add]").onclick = () => input.click();
    input.onchange = async () => { const f = input.files[0]; if (!f) return; d.close(); try { await uploadNotebook(f); } catch (e) { page("showNotice")(`<b>Couldn't add ${escH(f.name)}.</b> ${escH(e.message)}`); } };
    row.querySelector("[data-samples]").onclick = async () => { try { const p = await copySamples(); d.close(); await openPath(p); } catch (e) { alertIn(body, e.message); } };
    body.append(row);
  }
  function alertIn(body, text) { const r = document.createElement("div"); r.className = "res bad"; r.textContent = text; body.append(r); }

  async function upload(file, folder) {
    const r = await api("POST", "upload?" + q({ folder: folder || ".", name: file.name }), file);
    return r;
  }
  // Adding a notebook the student already has asks what to do, so that there is only ever one copy of it.
  async function uploadNotebook(file, onExists) {
    const r = await api("POST", "upload?" + q({ kind: "notebook", name: file.name, on_exists: onExists || "" }), file);
    if (r.exists) {
      const choice = await askExisting(file, r);
      return choice ? uploadNotebook(file, choice) : null;
    }
    await openPath(r.saved);
    if (r.replaced) page("showNotice")(`<b>${escH(r.name)} was replaced</b> with the file you chose.`);
    return r;
  }
  function askExisting(file, info) {
    return new Promise((resolve) => {
      const { d, body } = dialog("ntExists", "You already have this notebook");
      const saved = info.modified ? ` (last saved ${escH(fmtTime(info.modified))})` : "";
      const differs = info.same_as_added === false
        ? `<p class="h">The file you chose is not the one you added${info.added ? " on " + escH(fmtTime(info.added)) : ""}: your lecturer may have updated it.</p>` : "";
      body.innerHTML = `<p>The tutor already keeps <b>${escH(file.name)}</b>${saved}, with your work in it.</p>${differs}
        <div class="row"><button class="btn primary" type="button" data-open>Open your saved copy (keeps your work)</button>
        <button class="btn" type="button" data-replace>Replace it with this file</button></div>
        <p class="h">Replacing it discards the work in your saved copy. Either way the tutor keeps one copy of the notebook.</p>`;
      let answer = null;
      body.querySelector("[data-open]").onclick = () => { answer = "open"; d.close(); };
      body.querySelector("[data-replace]").onclick = () => { answer = "replace"; d.close(); };
      d.addEventListener("close", () => resolve(answer), { once: true });
      d.showModal();
      body.querySelector("[data-open]").focus();
    });
  }
  async function uploadData(file) {
    const r = await upload(file, dirOf(current) || ".");
    refreshFiles();
    return r;
  }

  // ------------------------------------------------------------------ language-model setup
  let llmNode = null;
  async function describe(st) {
    if (!llmNode) return;
    try { st = st || await api("GET", "settings"); } catch { return; }
    const short = { gemini: "Gemini", anthropic: "Claude", openai: "OpenAI", ollama: "Ollama on this computer", "openai-compatible": "OpenAI-compatible server", none: "None" }[st.provider] || st.provider;
    const p = st.providers[st.provider] || {};
    const model = st.model_thorough || st.model_quick || p.thorough || p.quick || "";
    llmNode.textContent = st.provider === "none" ? "Not set up" : short + (model ? " · " + model : "");
  }
  async function setup() {
    const { d, body } = dialog("ntSetup", "Language model for the tutor");
    let st;
    try { st = await api("GET", "settings"); } catch (e) { body.innerHTML = `<div class="res bad">${escH(e.message)}</div>`; d.showModal(); return; }
    const P = st.providers;
    body.innerHTML = `
      <p class="h">The tutor needs a language model for explanations, questions and feedback. Python and the kit's own checks work without one. Choose what you have:</p>
      <label class="f">Provider<select data-k="provider">${Object.entries(P).map(([k, v]) => `<option value="${k}">${escH(v.label)}</option>`).join("")}</select></label>
      <div data-gem class="h"></div>
      <label class="f" data-keyrow>API key<input type="password" data-k="api_key" autocomplete="off" spellcheck="false"><span class="h" data-keyhint></span></label>
      <label class="f" data-urlrow>Server address<input type="text" data-k="base_url" spellcheck="false"><span class="h">For Ollama the default is http://localhost:11434. For LM Studio it is usually http://localhost:1234/v1.</span></label>
      <div class="row" data-modelrow><label class="f" style="flex:1">Fast model<input type="text" data-k="model_quick" list="ntModels" spellcheck="false"></label>
        <label class="f" style="flex:1">Thorough model<input type="text" data-k="model_thorough" list="ntModels" spellcheck="false"></label></div>
      <datalist id="ntModels"></datalist>
      <div class="row"><button class="btn" type="button" data-list>Show available models</button><button class="btn" type="button" data-test>Test the connection</button><span style="flex:1"></span><button class="btn primary" type="button" data-save>Save</button></div>
      <div class="res" data-res hidden></div>
      <p class="h">Your key is kept only on this computer, in <code>${escH(st.config_file)}</code>. It is not written into notebooks, it is not given to the notebook's Python, and this page never receives it back.</p>`;
    const $k = (k) => body.querySelector(`[data-k="${k}"]`);
    const resBox = body.querySelector("[data-res]");
    const show = (text, cls) => { resBox.hidden = false; resBox.className = "res " + (cls || ""); resBox.textContent = text; };
    $k("provider").value = st.provider;
    $k("base_url").value = st.base_url || "";
    $k("model_quick").value = st.model_quick || "";
    $k("model_thorough").value = st.model_thorough || "";
    let stored = { provider: st.provider, has_key: st.has_key, key_hint: st.key_hint };
    function refresh() {
      const p = $k("provider").value, info = P[p] || {};
      body.querySelector("[data-keyrow]").hidden = !info.needs_key;
      body.querySelector("[data-urlrow]").hidden = !info.needs_url;
      body.querySelector("[data-modelrow]").hidden = p === "none";
      $k("base_url").placeholder = info.default_url || "";
      $k("model_quick").placeholder = info.quick || (p === "none" ? "" : "choose from the list");
      $k("model_thorough").placeholder = info.thorough || (p === "none" ? "" : "choose from the list");
      const kept = stored.provider === p && stored.has_key;
      $k("api_key").placeholder = kept ? `A key is stored (${stored.key_hint || "hidden"}). Leave empty to keep it.` : "Paste your key here";
      body.querySelector("[data-keyhint]").innerHTML = info.key_url ? `Create one at <a href="${info.key_url}" target="_blank" rel="noopener">${escH(info.key_url.replace(/^https:\/\//, ""))}</a>.` : "";
      body.querySelector("[data-gem]").innerHTML = p === "gemini"
        ? "Gemini: sign in to Google AI Studio and create an API key. If AI Studio refuses with your university account, use a personal Google account or ask your lecturer."
        : p === "ollama" ? "Ollama runs open-weight models on your own computer, with no key and nothing sent online. Install it from ollama.com, then run for example <code>ollama pull llama3.2</code>. Small models are slower and less accurate than the online ones."
        : p === "none" ? "The tutor's explanations and feedback are switched off. Your lecturer's own questions and the kit's checks still work." : "";
    }
    $k("provider").onchange = () => { refresh(); resBox.hidden = true; };
    refresh();
    const form = () => ({ provider: $k("provider").value, api_key: $k("api_key").value.trim(), base_url: $k("base_url").value.trim(),
                          model_quick: $k("model_quick").value.trim(), model_thorough: $k("model_thorough").value.trim() });
    body.querySelector("[data-list]").onclick = async () => {
      show("Asking the provider for its models…");
      try {
        const r = await api("POST", "models", form());
        if (r.error) return show(r.error.message, "bad");
        const dl = body.querySelector("#ntModels"); dl.innerHTML = r.models.map((m) => `<option value="${escH(m)}">`).join("");
        show(r.models.length ? `${r.models.length} models available. Click a model box to pick one:\n${r.models.slice(0, 30).join(", ")}${r.models.length > 30 ? ", …" : ""}` : "The provider listed no models.", r.models.length ? "ok" : "bad");
      } catch (e) { show(e.message, "bad"); }
    };
    body.querySelector("[data-test]").onclick = async () => {
      show("Testing…");
      try {
        const r = await api("POST", "settings/test", form());
        if (r.error) show(`Not working: ${r.error.message}`, "bad");
        else show(`Working. ${r.model ? r.model + " " : ""}replied in ${r.seconds} s: “${String(r.text).trim().slice(0, 80)}”`, "ok");
      } catch (e) { show(e.message, "bad"); }
    };
    body.querySelector("[data-save]").onclick = async () => {
      try {
        const r = await api("PUT", "settings", form());
        stored = { provider: r.provider, has_key: r.has_key, key_hint: r.key_hint };
        describe(r);
        $k("api_key").value = "";
        window.NBT_HOST.configured = r.provider !== "none";
        show(r.provider === "none" ? "Saved. The tutor will not use a language model." : "Saved. The tutor will use these settings from now on.", "ok");
        const b = document.getElementById("tutorBanner"); if (b && window.NBT_HOST.configured) b.hidden = true;
        if (window.NBT_HOST.configured) page("showNotice")(null);
        refresh();
      } catch (e) { show(e.message, "bad"); }
    };
    d.showModal();
  }

  // ------------------------------------------------------------------ the host object
  window.NBT_HOST = {
    kind: "local",
    version: BOOT.version,
    configured: !!BOOT.configured,
    store,
    // lifecycle
    ready() {
      const start = BOOT.initial || prefs["last:" + BOOT.root] || null;
      const tryOpen = start ? openPath(start) : Promise.reject(new Error("no notebook"));
      tryOpen.catch(() => openDialog({ firstRun: true }));
    },
    changed(text) {
      if (!current) return;
      const hint = document.getElementById("saveHint");
      if (hint) hint.textContent = "Saving…";
      api("PUT", "notebook?" + q({ path: current }), { text })
        .then(() => { if (hint) { hint.textContent = "Saved"; hint.title = "Saved to " + current; } })
        .catch((e) => { if (hint) hint.textContent = "Not saved"; page("showNotice")(`<b>Your work could not be saved to ${escH(current)}.</b> ${escH(e.message)}`); });
    },
    modeChosen(m) { if (current) { prefs[modeKey()] = m; savePrefs(); } },
    // notebooks and files
    openDialog, uploadNotebook, uploadData, refreshFiles, reference,
    // Python
    async startKernel() { await nbKnown; return api("POST", "kernel/start", { path: current }); },
    async resetKernel() { await nbKnown; return api("POST", "kernel/start", { path: current, restart: true }); },
    async run(code) {
      running.count++;
      const stop = document.getElementById("interruptBtn");
      const t = setTimeout(() => { if (stop) stop.hidden = false; }, 700);   // only for cells that take a while
      try { const r = await api("POST", "run", { code }); setTimeout(refreshFiles, 50); return r; }
      catch (e) { return { error: { ename: "TutorError", evalue: e.message, traceback: "" }, results: [], figures: [], stdout: "", stderr: "" }; }
      finally { running.count--; clearTimeout(t); if (stop) stop.hidden = true; }
    },
    async vars() { try { return (await api("GET", "vars")).text; } catch { return "(unavailable)"; } },
    interrupt() {
      api("POST", "kernel/interrupt").catch(() => {});
      // Some work cannot be interrupted (on Windows, a long call inside a library); then only a restart helps.
      const n = ++running.stops;
      setTimeout(() => {
        if (running.count > 0 && running.stops === n)
          page("showNotice")("<b>This cell has not stopped.</b> Some work cannot be interrupted, for example a long call inside a library on Windows. <b>Restart Python</b> stops it; your variables are cleared, so run the cells above again.");
      }, 6000);
    },
    envLine() {
      const libs = (BOOT.libs || []).join(", ");
      return `Python ${BOOT.python || "3"} runs on the student's own computer in a Jupyter kernel started in the notebook's folder, with ${libs}${BOOT.kit ? " and ai-learning-kit " + BOOT.kit : ""}. Files are read and written by their path relative to the notebook and are saved on disk. Python can reach the internet. %pip works (reinstalling ai-learning-kit is skipped because the tutor provides it). input() does not work.`;
    },
    setup,
    describeLLM(node) { llmNode = node; describe(); },
  };

  // ------------------------------------------------------------------ the language model, in the shape the page expects
  function sample(prompt, opts = {}) { return ask(prompt, opts, false).then((r) => ({ text: r.text, truncated: !!r.truncated })); }
  sample.json = (prompt, opts = {}) => ask(prompt, opts, true).then((r) => r.json);
  async function ask(prompt, opts, json) {
    const r = await api("POST", "llm", { prompt, json, tier: opts.modelTier === "default" ? "default" : "quick" }, { signal: opts.signal });
    if (r.error) throw { code: r.error.code, message: r.error.message };
    return r;
  }
  // Inside VS Code's Simple Browser (the page is in a frame), links from the notebook would open in VS Code's
  // embedded browser, where sites such as YouTube refuse to play. Ask the tutor's server to open them in the
  // computer's own browser instead. In a normal browser tab, links open in a new tab as usual.
  const framed = (() => { try { return window.top !== window.self; } catch { return true; } })();
  if (framed) {
    document.addEventListener("click", (e) => {
      const a = e.target && e.target.closest && e.target.closest("a[href]");
      if (!a) return;
      let url;
      try { url = new URL(a.getAttribute("href"), location.href); } catch { return; }
      if (!/^https?:$/.test(url.protocol) || url.origin === location.origin) return;
      e.preventDefault();
      api("POST", "open", { url: url.href })
        .then(() => page("showNotice")(`<b>Opened in your browser:</b> ${escH(url.hostname)}. Switch to your browser window to see it.`))
        .catch(() => window.open(url.href, "_blank", "noopener"));
    }, true);
  }

  window.claude = {
    use(name) {
      if (name === "sample") return Promise.resolve(sample);
      return Promise.resolve(null);
    },
  };
})();
