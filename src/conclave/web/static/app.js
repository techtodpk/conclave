/* Conclave app. Plain JavaScript, no build step. Text from the server is always set as
   text; only HTML the server has already rendered safely (answers, checks) is inserted. */
"use strict";

const view = document.getElementById("view");
const shell = document.getElementById("app");
let status = null;
let pollTimer = null;

// --- helpers ------------------------------------------------------------------------

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v; // only ever server-rendered, sanitised HTML
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: { "X-Conclave": "1" } };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("The Conclave app is not running. Start it again from the Conclave shortcut.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function plural(n, one, many) { return `${n} ${n === 1 ? one : (many || one + "s")}`; }
function money(v) {
  if (v === null || v === undefined) return "–";
  return v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(v >= 0.1 ? 3 : 4)}`;
}
function capMoney(v) { return `$${Number(v).toFixed(2)}`; }
function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
function toast(text) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 3200);
}
function errorBox(message) { return h("div", { class: "notice error", role: "alert" }, message); }
function labelBadge(label) {
  return h("span", { class: "label label-" + label.replaceAll(" ", "-") }, label);
}
function page(title, subtitle, ...right) {
  return h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, title), subtitle ? h("p", {}, subtitle) : null),
    h("div", { class: "row" }, ...right));
}
function setView(...nodes) {
  view.replaceChildren(...nodes);
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}
function loading(text = "Loading…") {
  return h("div", { class: "empty" }, h("span", { class: "spinner" }), " ", text);
}
function tabs(names, onPick, initial = 0) {
  const bar = h("div", { class: "tabs", role: "tablist" });
  const buttons = names.map((name, i) =>
    h("button", { role: "tab", class: i === initial ? "on" : "", onclick: () => pick(i) }, name));
  bar.append(...buttons);
  function pick(i) {
    buttons.forEach((b, j) => b.classList.toggle("on", i === j));
    onPick(i);
  }
  setTimeout(() => onPick(initial));
  return bar;
}

// --- status and navigation -------------------------------------------------------------

async function refreshStatus() {
  status = await api("/api/status");
  document.getElementById("version").textContent = `Conclave ${status.version}`;
  const pill = document.getElementById("month-pill");
  if (status.month !== undefined) {
    pill.hidden = false;
    pill.textContent = `This month ${money(status.month)} of ${capMoney(status.monthly_cap)}`;
  }
  document.getElementById("running-pill").hidden = !status.running;
  return status;
}

const routes = {
  ask: renderAsk,
  topics: renderTopics,
  topic: renderTopic,
  run: renderRun,
  search: renderSearch,
  spending: renderSpending,
  settings: renderSettings,
  setup: renderSetup,
};

async function router() {
  clearInterval(pollTimer);
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const name = parts[0] || "ask";
  if (!status) {
    try { await refreshStatus(); } catch (e) { setView(errorBox(e.message)); return; }
  }
  if (status.setup_needed && name !== "setup") { location.hash = "#/setup"; return; }
  shell.classList.toggle("bare", name === "setup");
  document.querySelectorAll("[data-nav]").forEach(a => {
    const key = a.dataset.nav;
    a.classList.toggle("active", key === name || (key === "topics" && (name === "topic" || name === "run")));
  });
  const render = routes[name] || renderAsk;
  try {
    await render(...parts.slice(1));
  } catch (e) {
    setView(errorBox(e.message));
  }
}
window.addEventListener("hashchange", router);

// --- setup wizard -------------------------------------------------------------------------

const COUNCILS = {
  lean: { title: "Lean", text: "Three models, two of them low-cost. Good for everyday questions.", cost: "Full run usually 5–15 cents" },
  balanced: { title: "Balanced (recommended)", text: "Claude, GPT and Gemini: three labs, three points of view.", cost: "Full run usually 10–30 cents" },
  full: { title: "Full", text: "Four models and a top-tier chairman, for decisions that matter.", cost: "Full run usually 20–60 cents" },
};

async function renderSetup(stepArg) {
  await refreshStatus();
  let step = Number(stepArg || 0);
  const total = 5;
  const steps = h("div", { class: "steps", "aria-hidden": "true" },
    ...Array.from({ length: total }, (_, i) => h("span", { class: i <= step ? "on" : "" })));
  const go = (n) => { location.hash = `#/setup/${n}`; };
  const card = h("div", { class: "card wizard" }, steps);
  setView(card);

  if (step === 0) {
    card.append(
      h("h1", {}, "Welcome to Conclave"),
      h("p", {}, "Conclave asks several AI models the same question, has them check each other's work and the web, and keeps what they conclude on your computer, so every later question on a topic starts from what you already know."),
      h("h3", {}, "What you need"),
      h("ul", {},
        h("li", {}, "An OpenRouter account. It is one account for every AI model; you pay only for what you use."),
        h("li", {}, "About $5 of credit to start. A quick question costs about 1 cent; a full council run usually 10 to 30 cents.")),
      h("p", { class: "muted small" }, "Setup takes about three minutes. Your research stays in a folder on this computer."),
      h("div", { class: "actions" }, h("span"), h("button", { class: "primary big", onclick: () => go(1) }, "Get started")));
    return;
  }

  if (step === 1) {
    const def = status.store || "your home folder, in conclave-research";
    const input = h("input", { type: "text", id: "store", placeholder: "Leave empty to use the default" });
    const msg = h("div");
    card.append(
      h("h1", {}, "Where should your research live?"),
      h("p", {}, "Conclave saves every question, answer and conclusion as plain files in one folder. You can open them with any text editor, and back them up like any other folder."),
      h("div", { class: "field" },
        h("label", { for: "store" }, "Research folder"),
        input,
        h("div", { class: "hint" }, status.has_config ? `Already set: ${status.store}` : `Default: ${def}`)),
      msg,
      h("div", { class: "actions" },
        h("button", { onclick: () => go(0) }, "Back"),
        h("button", { class: "primary", onclick: async (e) => {
          e.target.disabled = true; msg.replaceChildren();
          try {
            const r = await api("/api/setup/store", { method: "POST", body: { path: input.value.trim() || null } });
            toast(`Research folder ready: ${r.store}`);
            go(2);
          } catch (err) { msg.append(errorBox(err.message)); e.target.disabled = false; }
        } }, "Continue")));
    if (status.has_config) input.disabled = true;
    return;
  }

  if (step === 2) {
    const input = h("input", { type: "password", id: "key", autocomplete: "off", placeholder: "sk-or-v1-…" });
    const msg = h("div");
    const already = status.key ? h("div", { class: "notice ok" }, `A key ending in …${status.key.ends} is already saved. Paste a new one only to replace it.`) : null;
    card.append(...[
      h("h1", {}, "Connect your OpenRouter account"),
      h("ol", { class: "howto" },
        h("li", {}, "Open ", h("a", { href: "https://openrouter.ai/keys", target: "_blank", rel: "noopener" }, "openrouter.ai/keys"), " and sign in (Google or email)."),
        h("li", {}, "Add credit under ", h("a", { href: "https://openrouter.ai/settings/credits", target: "_blank", rel: "noopener" }, "Credits"), ". $5 is plenty to start."),
        h("li", {}, "Click ", h("b", {}, "Create key"), ". Give it a name like “Conclave” and, for safety, a credit limit such as $10."),
        h("li", {}, "Copy the key and paste it below.")),
      already,
      h("div", { class: "field" }, h("label", { for: "key" }, "Your OpenRouter key"), input,
        h("div", { class: "hint" }, "It is checked with OpenRouter, then saved only on this computer. Conclave never shows it again.")),
      msg,
      h("div", { class: "actions" },
        h("button", { onclick: () => go(1) }, "Back"),
        h("div", { class: "row" },
          status.key ? h("button", { onclick: () => go(3) }, "Keep the saved key") : null,
          h("button", { class: "primary", onclick: async (e) => {
            e.target.disabled = true; msg.replaceChildren(h("div", { class: "notice info" }, h("span", { class: "spinner" }), " Checking with OpenRouter…"));
            try {
              const r = await api("/api/setup/key", { method: "POST", body: { key: input.value } });
              input.value = "";
              const left = r.remaining !== null && r.remaining !== undefined ? ` It can spend ${money(r.remaining)} more.` : "";
              await refreshStatus();
              if (r.other_key_in_use) {
                msg.replaceChildren(h("div", { class: "notice warn" },
                  `Your key was saved, but another key ending in …${r.other_key_in_use.ends} takes precedence, from ${r.other_key_in_use.source}. Remove it there to use the new one.`),
                  h("button", { class: "primary", onclick: () => go(3) }, "Continue anyway"));
                e.target.disabled = false;
                return;
              }
              toast(`Key accepted.${left}`);
              go(3);
            } catch (err) { msg.replaceChildren(errorBox(err.message)); e.target.disabled = false; }
          } }, "Check and save")))].filter(Boolean));
    input.focus();
    return;
  }

  if (step === 3) {
    const settings = await api("/api/settings");
    let chosen = settings.run.default_profile;
    const options = h("div", { class: "stack" });
    const draw = () => options.replaceChildren(...["lean", "balanced", "full"].filter(n => settings.profiles.some(p => p.name === n)).map(name => {
      const info = COUNCILS[name];
      const p = settings.profiles.find(x => x.name === name);
      return h("div", { class: "choice" + (chosen === name ? " on" : ""), role: "radio", tabindex: "0", "aria-checked": String(chosen === name),
        onclick: () => { chosen = name; draw(); }, onkeydown: (e) => { if (e.key === " " || e.key === "Enter") { chosen = name; draw(); } } },
        h("h3", {}, info.title),
        h("div", {}, info.text),
        h("div", { class: "small muted" }, `Members: ${p.members.join(", ")}. Writes the answer: ${p.chairman}.`),
        h("div", { class: "small" }, info.cost));
    }));
    draw();
    const msg = h("div");
    card.append(
      h("h1", {}, "Choose your council"),
      h("p", {}, "A council is the set of models that answer and review each other. You can change it any time, or build your own, in Settings."),
      options, msg,
      h("div", { class: "actions" },
        h("button", { onclick: () => go(2) }, "Back"),
        h("button", { class: "primary", onclick: async () => {
          try { await api("/api/settings", { method: "PUT", body: { run: { default_profile: chosen } } }); go(4); }
          catch (err) { msg.replaceChildren(errorBox(err.message)); }
        } }, "Continue")));
    return;
  }

  if (step === 4) {
    const s = await api("/api/settings");
    const full = h("input", { type: "number", id: "full", min: "0.05", step: "0.05", value: s.budget.full_run_usd });
    const quick = h("input", { type: "number", id: "quick", min: "0.01", step: "0.01", value: s.budget.quick_run_usd });
    const month = h("input", { type: "number", id: "month", min: "1", step: "1", value: s.budget.monthly_usd });
    const msg = h("div");
    card.append(
      h("h1", {}, "Set your spending limits"),
      h("p", {}, "Before anything is sent, Conclave works out the most a question could cost and refuses it if that is over your limit. Real runs usually cost far less than the limit."),
      h("div", { class: "fields" },
        h("div", { class: "field" }, h("label", { for: "full" }, "Most for one full run ($)"), full, h("div", { class: "hint" }, "The whole council, with web search")),
        h("div", { class: "field" }, h("label", { for: "quick" }, "Most for one quick run ($)"), quick, h("div", { class: "hint" }, "One model, no web search")),
        h("div", { class: "field" }, h("label", { for: "month" }, "Most per month ($)"), month, h("div", { class: "hint" }, "Full runs pause when it is reached"))),
      msg,
      h("div", { class: "actions" },
        h("button", { onclick: () => go(3) }, "Back"),
        h("button", { class: "primary", onclick: async () => {
          try {
            await api("/api/settings", { method: "PUT", body: { budget: { full_run_usd: full.value, quick_run_usd: quick.value, monthly_usd: month.value } } });
            await refreshStatus();
            toast("All set.");
            location.hash = "#/ask/first";
          } catch (err) { msg.replaceChildren(errorBox(err.message)); }
        } }, "Finish")));
  }
}

// --- ask -------------------------------------------------------------------------------

const STAGES = [
  ["research", "Research", "Each member answers on its own"],
  ["critique", "Review", "Members review each other's answers, authors hidden"],
  ["verify", "Check", "Key claims are checked against the pages members cited"],
  ["synthesis", "One-page answer", "The chairman writes the answer"],
  ["memory", "Memory", "The topic's memory is updated"],
];

async function renderAsk(arg) {
  await refreshStatus();
  if (status.running) { renderJob(status.running); return; }
  const settings = await api("/api/settings");
  const topics = await api("/api/topics");
  let mode = "quick";

  const question = h("textarea", { id: "q", placeholder: "What do you want the council to research?", rows: "4" });
  if (arg === "first") question.value = "What are the pros and cons of electric cars versus hybrids for a family in 2026?";
  const topic = h("input", { type: "text", id: "topic", list: "topic-list", placeholder: "general", autocomplete: "off" });
  const list = h("datalist", { id: "topic-list" }, ...topics.map(t => h("option", { value: t.name })));
  const council = h("select", { id: "council" }, ...settings.profiles.map(p =>
    h("option", { value: p.name, selected: p.name === settings.run.default_profile }, p.name)));
  const search = h("input", { type: "checkbox", id: "web", checked: settings.search.enabled });
  const fresh = h("input", { type: "checkbox", id: "fresh" });
  const hint = h("div", { class: "hint" });
  const quickBtn = h("button", { type: "button", onclick: () => setMode("quick") }, "Quick");
  const fullBtn = h("button", { type: "button", onclick: () => setMode("full") }, "Full council");
  const searchRow = h("label", { class: "check" }, search, h("span", {}, "Search the web and check key claims against sources"));
  const msg = h("div");

  function setMode(m) {
    mode = m;
    quickBtn.classList.toggle("on", m === "quick");
    fullBtn.classList.toggle("on", m === "full");
    searchRow.hidden = m !== "full";
    hint.textContent = m === "quick"
      ? `One model answers, using what this topic already knows. About 1 cent; never more than ${capMoney(settings.budget.quick_run_usd)}.`
      : `Every member answers${settings.search.enabled ? " and searches the web" : ""}, they review each other, and the chairman writes one page. One to two minutes; usually 10–30 cents, never more than ${capMoney(settings.budget.full_run_usd)}.`;
  }
  setMode(settings.run.default_mode === "full" ? "full" : "quick");

  const submit = h("button", { class: "primary big", type: "submit" }, "Ask");
  const form = h("form", { class: "card", onsubmit: async (e) => {
    e.preventDefault();
    submit.disabled = true; msg.replaceChildren();
    try {
      const started = await api("/api/ask", { method: "POST", body: {
        question: question.value, topic: topic.value.trim() || "general", full: mode === "full",
        profile: council.value, no_search: !search.checked, fresh: fresh.checked } });
      await refreshStatus();
      renderJob(started.job, started);
    } catch (err) { msg.replaceChildren(errorBox(err.message)); submit.disabled = false; }
  } },
    h("div", { class: "field" }, h("label", { for: "q" }, "Your question"), question),
    h("div", { class: "fields" },
      h("div", { class: "field" }, h("label", { for: "topic" }, "Topic"), topic, list,
        h("div", { class: "hint" }, "Questions on the same topic build on each other.")),
      h("div", { class: "field" }, h("label", { for: "council" }, "Council"), council)),
    h("div", { class: "field" }, h("label", {}, "How thorough"), h("div", { class: "segmented", role: "group" }, quickBtn, fullBtn), hint),
    h("div", { class: "field" }, searchRow,
      h("label", { class: "check" }, fresh, h("span", {}, "Ignore what this topic already knows (fresh start)"))),
    msg,
    h("div", { class: "row between" }, h("span", { class: "muted small" }, `This month: ${money(status.month)} of ${capMoney(status.monthly_cap)}`), submit));

  setView(page("Ask the council", "Several AI models research your question and check each other."), form);
  question.focus();
}

function renderJob(jobId, startInfo) {
  const stageEls = {};
  const list = h("ol", { class: "stages" });
  for (const [key, title, text] of STAGES) {
    const chips = h("div", { class: "chips" });
    const detail = h("div", { class: "small muted" }, text);
    const dot = h("div", { class: "dot" }, String(list.children.length + 1));
    const li = h("li", { class: "stage" }, dot, h("div", {}, h("div", { class: "title" }, title), detail, chips));
    stageEls[key] = { li, chips, detail, dot, calls: {} };
    list.append(li);
  }
  const timer = h("span", { class: "muted" }, "0 s");
  const heading = h("h2", {}, "Working on it…");
  const questionLine = h("p", { class: "muted" });
  const box = h("div", { class: "card" }, h("div", { class: "row between" }, heading, timer), questionLine, list);
  const result = h("div");
  setView(page("Ask the council", "You can leave this page; the run carries on and is saved."), box, result);

  if (startInfo && startInfo.mode === "quick") {
    for (const k of ["critique", "verify", "synthesis", "memory"]) stageEls[k].li.hidden = true;
    stageEls.research.detail.textContent = `${startInfo.chairman} answers, using what the topic already knows`;
  }
  let since = 0;
  let busy = false;
  let current = null;
  let mode = startInfo ? startInfo.mode : null;

  function activate(stage, detail) {
    if (current && current !== stage) {
      stageEls[current].li.classList.remove("active");
      stageEls[current].li.classList.add("done");
      stageEls[current].dot.textContent = "✓";
    }
    current = stage;
    const s = stageEls[stage];
    if (!s) return;
    s.li.hidden = false;
    s.li.classList.add("active");
    if (detail) s.detail.textContent = detail.charAt(0).toUpperCase() + detail.slice(1);
  }

  async function poll() {
    if (busy) return; // never two requests at once, or events would be shown twice
    busy = true;
    let data;
    try { data = await api(`/api/jobs/${jobId}?since=${since}`); }
    catch (e) { clearInterval(pollTimer); result.replaceChildren(errorBox(e.message)); return; }
    finally { busy = false; }
    since = data.next;
    mode = data.mode;
    questionLine.textContent = `“${data.question}” · topic ${data.topic} · ${data.mode} run`;
    timer.textContent = `${Math.round(data.elapsed)} s`;
    if (mode === "quick") for (const k of ["critique", "verify", "synthesis", "memory"]) stageEls[k].li.hidden = true;
    for (const ev of data.events) {
      if (ev.type === "stage") activate(ev.stage, ev.detail);
      else if (ev.type === "step") { const s = stageEls[ev.stage]; if (s) s.detail.textContent = ev.detail.charAt(0).toUpperCase() + ev.detail.slice(1); }
      else if (ev.type === "call") {
        const s = stageEls[ev.stage];
        if (!s) continue;
        const short = ev.model.split("/").pop();
        if (ev.state === "started") {
          const chip = h("span", { class: "chip running" }, h("span", { class: "spinner" }), short);
          chip.dataset.model = ev.model;
          s.chips.append(chip);
          continue;
        }
        const chip = [...s.chips.children].find(c => c.dataset.model === ev.model && c.classList.contains("running"))
          || s.chips.appendChild(h("span", { class: "chip" }));
        chip.className = "chip " + (ev.state === "done" ? "done" : "failed");
        const extra = ev.state === "done"
          ? [ev.cost !== null && ev.cost !== undefined ? money(ev.cost) : null,
             ev.sources ? plural(ev.sources, "source") : null,
             ev.search_failed ? "answered without search" : null,
             ev.retried_without_reasoning ? "asked again without thinking" : null,
             ev.cut_off ? "cut off" : null].filter(Boolean).join(" · ")
          : "failed";
        chip.replaceChildren(ev.state === "done" ? "✓ " : "✕ ", short, extra ? ` · ${extra}` : "");
        if (ev.error) chip.title = ev.error;
      }
    }
    if (data.state !== "running") {
      clearInterval(pollTimer);
      if (current) { stageEls[current].li.classList.remove("active"); stageEls[current].li.classList.add("done"); stageEls[current].dot.textContent = "✓"; }
      for (const [k] of STAGES) if (!stageEls[k].li.classList.contains("done")) stageEls[k].li.classList.add("skipped");
      await refreshStatus();
      if (data.state === "failed") {
        heading.textContent = "The run did not finish";
        result.replaceChildren(errorBox(data.error), h("a", { class: "button", href: "#/ask" }, "Ask again"));
        return;
      }
      heading.textContent = "Done";
      showResult(result, data.result);
    }
  }
  poll();
  pollTimer = setInterval(poll, 1200);
}

function showResult(container, r) {
  const ev = r.evidence;
  const facts = h("div", { class: "meta" },
    h("span", {}, `Cost ${money(r.cost)} of ${capMoney(r.cap)}`),
    h("span", {}, `This month ${money(r.month)} of ${capMoney(r.monthly_cap)}`),
    ev ? h("span", {}, `${ev.distinct_sources} pages cited`) : null,
    ev && ev.claims_checked ? h("span", {}, `${ev.verified} of ${ev.claims_checked} key claims verified`) : null);
  const answer = h("div", { class: "card" },
    h("div", { class: "prose", html: r.html || "<p>No answer was written.</p>" }));
  const extras = h("div", { class: "card flat" }, facts);
  if (!r.has_page && r.changes && r.changes.length) {
    extras.append(h("h3", { style: "margin-top:14px" }, "What changed in this topic's memory"),
      h("ul", { class: "small" }, ...r.changes.map(c => h("li", {}, c.replace(/^- /, "")))));
  }
  for (const note of r.notes || []) extras.append(h("div", { class: "notice warn small" }, note));
  if (r.stopped) extras.append(h("div", { class: "notice warn small" }, r.stopped));
  extras.append(h("div", { class: "row", style: "margin-top:12px" },
    r.run ? h("a", { class: "button", href: `#/run/${encodeURIComponent(r.topic)}/${encodeURIComponent(r.run)}` }, "See everything in this run") : null,
    h("a", { class: "button", href: `#/topic/${encodeURIComponent(r.topic)}` }, "Open the topic"),
    h("a", { class: "button primary", href: "#/ask" }, "Ask another")));
  container.replaceChildren(answer, extras);
}

// --- topics ---------------------------------------------------------------------------

async function renderTopics() {
  setView(page("Topics", "What the council has concluded, topic by topic."), loading());
  const topics = await api("/api/topics");
  if (!topics.length) {
    setView(page("Topics", "What the council has concluded, topic by topic."),
      h("div", { class: "card empty" }, h("p", {}, "No topics yet."), h("a", { class: "button primary", href: "#/ask" }, "Ask your first question")));
    return;
  }
  setView(page("Topics", "What the council has concluded, topic by topic."),
    h("div", { class: "grid" }, ...topics.map(t => h("a", { class: "card topic-card", href: `#/topic/${encodeURIComponent(t.name)}` },
      h("h3", {}, t.name),
      h("div", { class: "meta" },
        h("span", {}, plural(t.claims, "claim")),
        h("span", {}, plural(t.open_disputes, "open dispute")),
        h("span", {}, plural(t.runs, "run"))),
      h("div", { class: "small muted", style: "margin-top:6px" }, t.last_run ? `Last run ${t.last_run}` : "No runs yet", t.has_notes ? " · has your notes" : "")))));
}

async function renderTopic(name) {
  setView(loading());
  const t = await api(`/api/topics/${encodeURIComponent(name)}`);
  const active = t.claims.filter(c => !c.retired);
  const retired = t.claims.filter(c => c.retired);
  const open = t.disputes.filter(d => !d.resolved);
  const resolved = t.disputes.filter(d => d.resolved);
  const body = h("div");
  const counts = {};
  for (const c of active) counts[c.label] = (counts[c.label] || 0) + 1;

  const head = page(t.topic, `${plural(active.length, "claim")} · ${plural(open.length, "open dispute")} · ${plural(t.runs.length, "run")}`,
    h("a", { class: "button primary", href: "#/ask" }, "Ask about this topic"));

  function claimsTab() {
    const showRetired = h("input", { type: "checkbox", id: "retired" });
    const listEl = h("ul", { class: "claims" });
    const draw = () => {
      const items = showRetired.checked ? [...active, ...retired] : active;
      listEl.replaceChildren(...(items.length ? items.map(c => h("li", {},
        h("span", { class: "id" }, c.id),
        h("div", {},
          h("span", { class: c.retired ? "retired" : "" }, c.text), " ", labelBadge(c.label),
          h("div", { class: "small muted" }, c.retired ? `Retired ${c.retired}: ${c.retired_reason}` : `Added ${c.added}${c.updated ? `, changed ${c.updated}` : ""}`),
          c.history && c.history.length ? h("details", { class: "small" }, h("summary", {}, `Earlier wording (${c.history.length})`),
            ...c.history.map(x => h("div", { class: "muted" }, `${x.date}: ${x.text}${x.reason ? ` (changed because: ${x.reason})` : ""}`))) : null)))
        : [h("li", { class: "empty" }, "No claims yet. Full council runs on this topic add them.")]));
    };
    showRetired.addEventListener("change", draw);
    draw();
    body.replaceChildren(h("div", { class: "card" },
      h("div", { class: "row between" },
        h("div", { class: "row" }, ...Object.entries(counts).map(([l, n]) => h("span", {}, labelBadge(l), ` ${n}`))),
        retired.length ? h("label", { class: "check small" }, showRetired, `Show ${retired.length} retired`) : null),
      listEl,
      h("p", { class: "small muted", style: "margin-top:12px" }, "Verified: a cited web page states it. Agreed but unchecked: members agreed, but no page was checked. Claims change only through full council runs; add a note to correct the council.")));
  }

  function disputesTab() {
    body.replaceChildren(h("div", { class: "card" },
      h("h3", {}, "Open"),
      open.length ? h("ul", { class: "claims" }, ...open.map(d => h("li", {}, h("span", { class: "id" }, d.id), h("div", {}, d.text, h("div", { class: "small muted" }, `Opened ${d.opened}`))))) : h("p", { class: "muted" }, "None."),
      resolved.length ? h("h3", { style: "margin-top:16px" }, "Resolved") : null,
      resolved.length ? h("ul", { class: "claims" }, ...resolved.map(d => h("li", {}, h("span", { class: "id" }, d.id), h("div", {}, d.text, h("div", { class: "small muted" }, `Resolved ${d.resolved}: ${d.resolution}`))))) : null));
  }

  function notesTab() {
    const input = h("textarea", { rows: "2", placeholder: "Something the council should know, e.g. “We deploy on Linux.”" });
    const listEl = h("ul", { class: "claims" });
    const msg = h("div");
    const draw = (notes) => listEl.replaceChildren(...(notes.length ? notes.map(n => h("li", {},
      h("span", { class: "id" }, n.date.slice(5)),
      h("div", { class: "row between" },
        h("div", {}, n.text, n.added_by ? h("div", { class: "small muted" }, `Added by ${n.added_by}`) : null),
        h("button", { class: "danger small", onclick: async () => {
          if (!confirm("Remove this note?")) return;
          try { const r = await api(`/api/topics/${encodeURIComponent(t.topic)}/notes/${n.index}`, { method: "DELETE" }); t.notes = r.notes; draw(r.notes); }
          catch (e) { msg.replaceChildren(errorBox(e.message)); }
        } }, "Remove"))))
      : [h("li", { class: "empty" }, "No notes yet.")]));
    draw(t.notes);
    body.replaceChildren(h("div", { class: "card" },
      h("p", { class: "muted" }, "Your notes are read before every question on this topic, and they outrank the council's conclusions."),
      listEl,
      h("form", { style: "margin-top:12px", onsubmit: async (e) => {
        e.preventDefault(); msg.replaceChildren();
        try { const r = await api(`/api/topics/${encodeURIComponent(t.topic)}/notes`, { method: "POST", body: { text: input.value } }); input.value = ""; t.notes = r.notes; draw(r.notes); toast("Note added."); }
        catch (err) { msg.replaceChildren(errorBox(err.message)); }
      } }, input, msg, h("div", { class: "row", style: "margin-top:8px" }, h("button", { class: "primary", type: "submit" }, "Add note")))));
  }

  function runsTab() {
    body.replaceChildren(h("div", { class: "card" }, t.runs.length ? h("table", { class: "list" },
      h("thead", {}, h("tr", {}, h("th", {}, "Question"), h("th", {}, "Mode"), h("th", {}, "When"), h("th", { class: "num" }, "Checked"), h("th", { class: "num" }, "Cost"))),
      h("tbody", {}, ...t.runs.map(r => h("tr", {},
        h("td", {}, h("a", { href: `#/run/${encodeURIComponent(t.topic)}/${encodeURIComponent(r.name)}` }, r.question || r.name)),
        h("td", {}, r.mode), h("td", { class: "muted" }, when(r.started)),
        h("td", { class: "num" }, r.checked ? `${r.verified}/${r.checked}` : "–"),
        h("td", { class: "num" }, money(r.cost))))))
      : h("p", { class: "muted" }, "No runs yet.")));
  }

  setView(head, tabs([`Claims (${active.length})`, `Disputes (${open.length})`, `Your notes (${t.notes.length})`, `Runs (${t.runs.length})`],
    (i) => [claimsTab, disputesTab, notesTab, runsTab][i]()), body);
}

async function renderRun(topic, name) {
  setView(loading());
  const r = await api(`/api/topics/${encodeURIComponent(topic)}/runs/${encodeURIComponent(name)}`);
  const body = h("div");
  const ev = r.evidence;
  const head = page(r.question || r.run, null);
  const facts = h("div", { class: "meta", style: "margin:-8px 0 16px" },
    h("a", { href: `#/topic/${encodeURIComponent(r.topic)}` }, `Topic ${r.topic}`),
    h("span", {}, `${r.mode} run`), h("span", {}, when(r.started)),
    r.profile ? h("span", {}, `council ${r.profile}`) : null,
    h("span", {}, `cost ${money(r.cost)}`),
    ev && ev.claims_checked ? h("span", {}, `${ev.verified} of ${ev.claims_checked} claims verified`) : null);

  const names = [];
  const draws = [];
  const add = (label, fn) => { names.push(label); draws.push(fn); };
  add(r.final_html ? "One-page answer" : "Answer", () => body.replaceChildren(h("div", { class: "card" },
    h("div", { class: "prose", html: r.final_html || (r.answers[0] ? r.answers[0].html : "<p>No answer saved.</p>") }))));
  if (r.final_html && r.answers.length) add(`Members' answers (${r.answers.length})`, () => body.replaceChildren(...r.answers.map(a =>
    h("div", { class: "card" }, h("h3", {}, a.letter ? `Response ${a.letter} · ` : "", a.model), h("div", { class: "prose", html: a.html })))));
  if (r.critiques.length) add(`Reviews (${r.critiques.length})`, () => body.replaceChildren(...r.critiques.map(a =>
    h("div", { class: "card" }, h("h3", {}, `Review by ${a.model}`), h("div", { class: "prose", html: a.html })))));
  if (r.verification_html) add("Claim checks", () => body.replaceChildren(h("div", { class: "card" }, h("div", { class: "prose", html: r.verification_html }))));
  if (r.sources.length) add(`Sources (${r.sources.length})`, () => body.replaceChildren(h("div", { class: "card" }, h("table", { class: "list" },
    h("thead", {}, h("tr", {}, h("th", {}, "Page"), h("th", {}, "Cited by"), h("th", {}, "Read"), h("th", {}, "Used to check"))),
    h("tbody", {}, ...r.sources.map(s => h("tr", {},
      h("td", {}, h("a", { href: /^https?:\/\//.test(s.url) ? s.url : "#", target: "_blank", rel: "noopener noreferrer" }, s.title || s.url)),
      h("td", { class: "small" }, (s.cited_by || []).map(m => m.split("/").pop()).join(", ")),
      h("td", { class: "small" }, s.fetched ? "yes" : s.fetch_error ? `no (${s.fetch_error})` : "–"),
      h("td", { class: "small" }, (s.verdicts || []).join("; ") || "–"))))))));
  add("Cost and timing", () => body.replaceChildren(h("div", { class: "card" },
    h("table", { class: "list" },
      h("thead", {}, h("tr", {}, h("th", {}, "Stage"), h("th", {}, "Model"), h("th", {}, "Result"), h("th", { class: "num" }, "Time"), h("th", { class: "num" }, "Cost"))),
      h("tbody", {}, ...r.calls.map(c => h("tr", {}, h("td", {}, c.stage), h("td", {}, c.model),
        h("td", { class: "small" }, c.status === "ok" ? "ok" : c.error || c.status),
        h("td", { class: "num" }, c.seconds ? `${c.seconds} s` : "–"), h("td", { class: "num" }, money(c.cost_usd)))))),
    ...(r.notes || []).map(n => h("div", { class: "notice warn small" }, n)))));
  setView(head, facts, tabs(names, (i) => draws[i]()), body);
}

// --- search ------------------------------------------------------------------------------

async function renderSearch(q) {
  const input = h("input", { type: "search", id: "s", placeholder: "Search questions, answers, conclusions and notes", value: q || "" });
  const results = h("div");
  const form = h("form", { class: "card", onsubmit: (e) => { e.preventDefault(); location.hash = `#/search/${encodeURIComponent(input.value.trim())}`; } },
    h("div", { class: "row" }, h("div", { style: "flex:1" }, input), h("button", { class: "primary", type: "submit" }, "Search")));
  setView(page("Search", "Everything the council has written, and your notes."), form, results);
  input.focus();
  if (!q) return;
  results.replaceChildren(loading("Searching…"));
  const hits = await api(`/api/search?q=${encodeURIComponent(q)}`);
  if (!hits.length) { results.replaceChildren(h("div", { class: "card empty" }, "Nothing found.")); return; }
  const words = q.toLowerCase().split(/\s+/).filter(w => w.length > 1);
  const mark = (text) => {
    const span = h("span", { class: "snippet" });
    const re = new RegExp(`(${words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "ig");
    for (const part of text.split(re)) span.append(words.includes(part.toLowerCase()) ? h("mark", {}, part) : part);
    return span;
  };
  results.replaceChildren(h("div", { class: "card" }, h("ul", { class: "claims" }, ...hits.map(hit => h("li", {},
    h("span", { class: "id" }, hit.kind),
    h("div", {},
      hit.run ? h("a", { href: `#/run/${encodeURIComponent(hit.topic)}/${encodeURIComponent(hit.run)}` }, `${hit.topic} · ${hit.run}`)
        : hit.topic ? h("a", { href: `#/topic/${encodeURIComponent(hit.topic)}` }, hit.topic) : null,
      h("div", { class: "small" }, mark(hit.snippet))))))));
}

// --- spending ---------------------------------------------------------------------------

async function renderSpending() {
  setView(loading());
  const s = await api("/api/spending");
  const share = Math.min(1, s.month / s.monthly_cap);
  const bar = h("div", { class: "bar" + (share >= 1 ? " over" : share > 0.8 ? " high" : "") }, h("span", { style: `width:${(share * 100).toFixed(1)}%` }));
  setView(page("Spending", "What your questions have cost, from each run's own record."),
    h("div", { class: "grid" },
      h("div", { class: "card" }, h("div", { class: "muted small" }, "This month"), h("div", { class: "stat" }, money(s.month)), bar,
        h("div", { class: "small muted", style: "margin-top:6px" }, `of your ${capMoney(s.monthly_cap)} monthly limit`)),
      h("div", { class: "card" }, h("div", { class: "muted small" }, "Limits per run"),
        h("div", {}, `Full council: ${capMoney(s.full_cap)}`), h("div", {}, `Quick: ${capMoney(s.quick_cap)}`),
        h("a", { class: "small", href: "#/settings" }, "Change limits"))),
    h("div", { class: "card" }, h("h2", {}, "By month"), s.months.length ? h("table", { class: "list" },
      h("thead", {}, h("tr", {}, h("th", {}, "Month"), h("th", { class: "num" }, "Runs"), h("th", { class: "num" }, "Total"))),
      h("tbody", {}, ...s.months.map(m => h("tr", {}, h("td", {}, m.month), h("td", { class: "num" }, m.runs), h("td", { class: "num" }, money(m.total))))))
      : h("p", { class: "muted" }, "No runs yet.")),
    h("div", { class: "card" }, h("h2", {}, "Recent runs"), s.runs.length ? h("table", { class: "list" },
      h("thead", {}, h("tr", {}, h("th", {}, "Question"), h("th", {}, "Topic"), h("th", {}, "Mode"), h("th", {}, "When"), h("th", { class: "num" }, "Cost"))),
      h("tbody", {}, ...s.runs.slice(0, 30).map(r => h("tr", {},
        h("td", {}, h("a", { href: `#/run/${encodeURIComponent(r.topic)}/${encodeURIComponent(r.name)}` }, r.question || r.name)),
        h("td", {}, r.topic), h("td", {}, r.mode), h("td", { class: "muted small" }, when(r.started)), h("td", { class: "num" }, money(r.cost))))))
      : h("p", { class: "muted" }, "No runs yet.")),
    h("div", { class: "card" }, h("h2", {}, "Which models the others rank highest"),
      h("p", { class: "small muted" }, "From your own full runs: each review ranks the other answers with the authors hidden. 0 means always ranked best, 1 always worst. Few runs make for a noisy ranking."),
      s.leaderboard.length ? h("table", { class: "list" },
        h("thead", {}, h("tr", {}, h("th", {}, "Model"), h("th", { class: "num" }, "Score"), h("th", { class: "num" }, "Ranked first"), h("th", { class: "num" }, "Rankings"))),
        h("tbody", {}, ...s.leaderboard.map(p => h("tr", {}, h("td", {}, p.model), h("td", { class: "num" }, p.score.toFixed(2)), h("td", { class: "num" }, p.firsts), h("td", { class: "num" }, p.rankings)))))
        : h("p", { class: "muted" }, "No rankings yet. Full council runs record them.")));
}

// --- settings ------------------------------------------------------------------------------

async function renderSettings() {
  setView(loading());
  let s = await api("/api/settings");
  const msg = h("div");

  const save = async (bodyData, done = "Saved.") => {
    msg.replaceChildren();
    try { s = await api("/api/settings", { method: "PUT", body: bodyData }); toast(done); await refreshStatus(); return true; }
    catch (e) { msg.replaceChildren(errorBox(e.message)); window.scrollTo(0, 0); return false; }
  };

  const keyCard = h("div", { class: "card" }, h("h2", {}, "OpenRouter key"),
    s.key ? h("p", {}, `A key ending in …${s.key.ends} is in use, from ${s.key.source}.`) : h("p", { class: "notice warn" }, "No key saved."),
    h("a", { class: "button", href: "#/setup/2" }, s.key ? "Replace the key" : "Add a key"));

  const def = h("select", { id: "def" }, ...s.profiles.map(p => h("option", { value: p.name, selected: p.name === s.run.default_profile }, p.name)));
  const defMode = h("select", { id: "mode" }, h("option", { value: "quick", selected: s.run.default_mode === "quick" }, "Quick"), h("option", { value: "full", selected: s.run.default_mode === "full" }, "Full council"));
  const councils = h("div", { class: "stack" });
  const drawCouncils = () => councils.replaceChildren(...s.profiles.map(p => h("div", { class: "card flat", style: "margin:0" },
    h("div", { class: "row between" }, h("h3", { style: "margin:0" }, p.name, p.name === s.run.default_profile ? h("span", { class: "pill", style: "margin-left:8px" }, "default") : null),
      h("div", { class: "row" },
        h("button", { onclick: () => councilEditor(p) }, "Edit"),
        p.name !== s.run.default_profile ? h("button", { class: "danger", onclick: async () => {
          if (!confirm(`Delete the council “${p.name}”?`)) return;
          try { s = await api(`/api/councils/${encodeURIComponent(p.name)}`, { method: "DELETE" }); drawCouncils(); toast("Council deleted."); }
          catch (e) { msg.replaceChildren(errorBox(e.message)); }
        } }, "Delete") : null)),
    h("div", { class: "small" }, h("b", {}, "Members: "), p.members.join(", ")),
    h("div", { class: "small" }, h("b", {}, "Writes the answer: "), p.chairman, h("b", {}, "  ·  Checks claims: "), p.checker),
    p.shared_vendors.length ? h("div", { class: "notice warn small" }, `More than one member comes from ${p.shared_vendors.join(", ")}. Models from one lab tend to share blind spots.`) : null)));
  drawCouncils();
  const editorSlot = h("div");

  function councilEditor(existing) {
    let chosen = existing ? [...existing.members] : [];
    let chair = existing ? existing.chairman : "";
    let checker = existing ? existing.checker : "";
    const name = h("input", { type: "text", id: "cname", value: existing ? existing.name : "", disabled: !!existing, placeholder: "e.g. mine" });
    const filter = h("input", { type: "search", placeholder: "Filter models, e.g. claude, gemini, deepseek" });
    const pickedEl = h("div");
    const chairSel = h("select", { id: "chair" });
    const checkSel = h("select", { id: "checker" });
    const tableBody = h("tbody");
    const err = h("div");
    let models = [];
    const drawPicked = () => {
      pickedEl.replaceChildren(...(chosen.length ? chosen.map(id => h("span", { class: "seat" }, id, h("button", { type: "button", "aria-label": `Remove ${id}`, onclick: () => { chosen = chosen.filter(x => x !== id); drawPicked(); drawTable(); } }, "✕"))) : [h("span", { class: "muted small" }, "Pick at least two members from the list below.")]));
      const opts = [...new Set([...chosen, chair, checker].filter(Boolean))];
      const fill = (sel, val) => sel.replaceChildren(h("option", { value: "" }, "Choose…"), ...[...new Set([...opts, ...models.map(m => m.id)])].map(id => h("option", { value: id, selected: id === val }, id)));
      fill(chairSel, chair); fill(checkSel, checker || chair);
    };
    const drawTable = () => {
      const f = filter.value.toLowerCase();
      const shown = models.filter(m => !f || m.id.toLowerCase().includes(f) || m.name.toLowerCase().includes(f)).slice(0, 150);
      tableBody.replaceChildren(...shown.map(m => h("tr", { class: chosen.includes(m.id) ? "on" : "" },
        h("td", {}, h("div", {}, m.name), h("div", { class: "small muted" }, m.id)),
        h("td", { class: "num small" }, `$${m.prompt.toFixed(2)} / $${m.completion.toFixed(2)}`),
        h("td", { class: "num" }, h("button", { type: "button", onclick: () => { chosen = chosen.includes(m.id) ? chosen.filter(x => x !== m.id) : [...chosen, m.id]; drawPicked(); drawTable(); } }, chosen.includes(m.id) ? "Remove" : "Add")))));
    };
    chairSel.addEventListener("change", () => { chair = chairSel.value; });
    checkSel.addEventListener("change", () => { checker = checkSel.value; });
    filter.addEventListener("input", drawTable);
    const panel = h("div", { class: "card" },
      h("h2", {}, existing ? `Edit “${existing.name}”` : "New council"),
      h("div", { class: "field" }, h("label", { for: "cname" }, "Name"), name, h("div", { class: "hint" }, "Lowercase letters, digits, - and _.")),
      h("div", { class: "field" }, h("label", {}, "Members"), pickedEl),
      h("div", { class: "field" }, filter),
      h("div", { class: "picker" }, h("table", { class: "list" }, h("thead", {}, h("tr", {}, h("th", {}, "Model"), h("th", { class: "num" }, "$ per million tokens in / out"), h("th", {}))), tableBody)),
      h("div", { class: "fields", style: "margin-top:14px" },
        h("div", { class: "field" }, h("label", { for: "chair" }, "Chairman (writes the one-page answer)"), chairSel),
        h("div", { class: "field" }, h("label", { for: "checker" }, "Checker (tests claims against sources)"), checkSel)),
      h("p", { class: "small muted" }, "Pick members from different labs: models from one lab tend to share blind spots."),
      err,
      h("div", { class: "row" },
        h("button", { class: "primary", onclick: async () => {
          err.replaceChildren();
          try {
            s = await api("/api/councils", { method: "POST", body: { name: name.value, members: chosen, chairman: chairSel.value, checker: checkSel.value, replace: !!existing } });
            editorSlot.replaceChildren(); drawCouncils(); def.replaceChildren(...s.profiles.map(p => h("option", { value: p.name, selected: p.name === s.run.default_profile }, p.name)));
            toast("Council saved.");
          } catch (e) { err.replaceChildren(errorBox(e.message)); }
        } }, "Save council"),
        h("button", { onclick: () => editorSlot.replaceChildren() }, "Cancel")));
    editorSlot.replaceChildren(panel);
    drawPicked();
    tableBody.replaceChildren(h("tr", {}, h("td", { colspan: "3", class: "empty" }, h("span", { class: "spinner" }), " Loading models from OpenRouter…")));
    api("/api/models").then(list => { models = list; drawPicked(); drawTable(); }).catch(e => tableBody.replaceChildren(h("tr", {}, h("td", { colspan: "3" }, errorBox(e.message)))));
    panel.scrollIntoView({ behavior: "smooth" });
  }

  const full = h("input", { type: "number", id: "bfull", min: "0.01", step: "0.05", value: s.budget.full_run_usd });
  const quick = h("input", { type: "number", id: "bquick", min: "0.01", step: "0.01", value: s.budget.quick_run_usd });
  const month = h("input", { type: "number", id: "bmonth", min: "1", step: "1", value: s.budget.monthly_usd });
  const searchOn = h("input", { type: "checkbox", id: "son", checked: s.search.enabled });
  const searches = h("input", { type: "number", id: "smax", min: "1", max: "10", value: s.search.max_searches });
  const claims = h("input", { type: "number", id: "claims", min: "0", max: "20", value: s.run.claims_checked });
  const tokens = h("input", { type: "number", id: "tokens", min: "200", step: "100", value: s.run.max_answer_tokens });
  const reasoning = h("select", { id: "reason" }, ...s.reasoning_levels.map(l => h("option", { value: l, selected: l === s.run.reasoning }, l)));

  setView(page("Settings", "Changes are saved to your Conclave config file."), msg,
    keyCard,
    h("div", { class: "card" }, h("h2", {}, "Councils"),
      h("div", { class: "fields" },
        h("div", { class: "field" }, h("label", { for: "def" }, "Default council"), def),
        h("div", { class: "field" }, h("label", { for: "mode" }, "Default thoroughness"), defMode)),
      h("div", { class: "row", style: "margin-bottom:14px" }, h("button", { onclick: () => save({ run: { default_profile: def.value, default_mode: defMode.value } }) }, "Save defaults"),
        h("button", { class: "primary", onclick: () => councilEditor(null) }, "New council")),
      councils),
    editorSlot,
    h("div", { class: "card" }, h("h2", {}, "Spending limits"),
      h("div", { class: "fields" },
        h("div", { class: "field" }, h("label", { for: "bfull" }, "Full run ($)"), full),
        h("div", { class: "field" }, h("label", { for: "bquick" }, "Quick run ($)"), quick),
        h("div", { class: "field" }, h("label", { for: "bmonth" }, "Per month ($)"), month)),
      h("button", { class: "primary", onclick: () => save({ budget: { full_run_usd: full.value, quick_run_usd: quick.value, monthly_usd: month.value } }) }, "Save limits")),
    h("div", { class: "card" }, h("h2", {}, "Web search and claim checks"),
      h("label", { class: "check field" }, searchOn, h("span", {}, "In full runs, members search the web and the checker tests key claims against the pages they cite")),
      h("div", { class: "fields" },
        h("div", { class: "field" }, h("label", { for: "smax" }, "Searches per member"), searches, h("div", { class: "hint" }, "About $0.007 each")),
        h("div", { class: "field" }, h("label", { for: "claims" }, "Key claims checked per run"), claims)),
      h("button", { class: "primary", onclick: () => save({ search: { enabled: searchOn.checked, max_searches: searches.value }, run: { claims_checked: claims.value } }) }, "Save")),
    h("div", { class: "card" }, h("h2", {}, "Advanced"),
      h("div", { class: "fields" },
        h("div", { class: "field" }, h("label", { for: "tokens" }, "Longest answer (tokens)"), tokens, h("div", { class: "hint" }, "About ¾ of a word each")),
        h("div", { class: "field" }, h("label", { for: "reason" }, "How hard models think first"), reasoning, h("div", { class: "hint" }, "Thinking is billed but not shown"))),
      h("button", { class: "primary", onclick: () => save({ run: { max_answer_tokens: tokens.value, reasoning: reasoning.value } }) }, "Save")),
    h("div", { class: "card" }, h("h2", {}, "Files"),
      h("p", { class: "small" }, h("b", {}, "Research folder: "), s.store),
      h("p", { class: "small" }, h("b", {}, "Config file: "), s.config_path),
      h("button", { class: "danger", onclick: async () => {
        if (!confirm("Close the Conclave app? You can start it again from its shortcut.")) return;
        try { await api("/api/quit", { method: "POST", body: {} }); }
        catch (e) { msg.replaceChildren(errorBox(e.message)); window.scrollTo(0, 0); return; }
        setView(h("div", { class: "card empty" }, h("h2", {}, "Conclave has closed."), h("p", {}, "You can close this tab. Start it again from the Conclave shortcut.")));
      } }, "Close the Conclave app")));
}

router();
