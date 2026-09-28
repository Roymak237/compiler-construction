/* --------------------------------------------------------------------
   Yaounde Urban-Speech Analyzer -- client script

   The browser renders; it never decides.  Every verdict, token, tree and
   number on screen arrives from /api/*, which is the same Analyzer the
   command line and the desktop window use.
   -------------------------------------------------------------------- */

"use strict";

const $  = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
};

let BOOT = null;

/* ====================================================================
   Splash
   ==================================================================== */

/**
 * Let the crest glow for the configured time, then fade the application in.
 * The delay is fixed rather than tied to the fetch, so the entrance looks the
 * same on a fast machine as on a slow one; the grammar is being built on the
 * server meanwhile, so nothing is wasted.
 */
function runSplash(ms) {
  setTimeout(reveal, ms);
}

function reveal() {
  const splash = $("splash");
  if (!splash || splash.classList.contains("gone")) return;
  splash.classList.add("gone");
  $("app").classList.add("shown");
  setTimeout(() => { splash.style.display = "none"; positionInk(); }, 750);
}

function reveal() {
  const splash = $("splash");
  splash.classList.add("gone");
  $("app").classList.add("shown");
  setTimeout(() => { splash.style.display = "none"; positionInk(); }, 700);
}

/* ====================================================================
   Boot
   ==================================================================== */

async function boot() {
  // Start the splash immediately; the default is used until the server
  // reports its own figure, so a slow first byte never delays the animation.
  runSplash(3000);

  try {
    const res = await fetch("/api/bootstrap");
    BOOT = await res.json();
  } catch (err) {
    $("status").textContent = "cannot reach the server";
    return;
  }
  if (BOOT.error) { $("status").textContent = BOOT.error; return; }

  $("version").textContent = "v" + BOOT.version;
  $("lamp").classList.add("ready");

  const g = BOOT.grammar;
  const unreviewed = g.unreviewed || 0;
  $("status").textContent =
    `${g.nonterminals} nonterminals \u00b7 ${g.cells} table entries \u00b7 ` +
    (unreviewed === 0
      ? `${g.conflicts.length} documented conflict${g.conflicts.length === 1 ? "" : "s"}`
      : `${unreviewed} unreviewed conflict${unreviewed === 1 ? "" : "s"}`);

  $("foot-course").textContent = BOOT.course + " \u00b7 " + BOOT.institution;
  $("foot-group").textContent =
    BOOT.group.map((m) => `${m.name} (${m.matricule})`).join("  \u00b7  ");

  buildExamples();
  buildCorpusPicker();
  renderSets();
  renderCorpus();
  renderStats();

  $("entry").value = BOOT.examples[0].text;
  analyze();
}

function buildExamples() {
  const box = $("examples");
  box.innerHTML = "";
  BOOT.examples.forEach((ex) => {
    const b = el("button", "chip", ex.label);
    b.title = ex.text;
    b.onclick = () => { $("entry").value = ex.text; analyze(); };
    box.appendChild(b);
  });
}

function buildCorpusPicker() {
  const sel = $("corpus-pick");
  BOOT.corpus.forEach((row, i) => {
    const o = el("option", null, `${row.sid}  \u2014  ${row.text}`);
    o.value = String(i);
    sel.appendChild(o);
  });
  sel.onchange = () => {
    if (sel.value === "") return;
    $("entry").value = BOOT.corpus[Number(sel.value)].text;
    analyze();
  };
}

/* ====================================================================
   Analysis
   ==================================================================== */

async function analyze() {
  const text = $("entry").value.trim();
  if (!text) {
    setVerdict(null, "Type a statement and press Analyze.", "");
    return;
  }

  const btn = $("run");
  btn.disabled = true;
  btn.textContent = "Analyzing\u2026";

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    const data = await res.json();

    if (data.error) {
      setVerdict(false, "Error", data.error);
      return;
    }
    setVerdict(data.accepted, data.verdict, data.reason);
    renderCounts(data);
    renderTokens(data);
    renderTree(data);
    renderTrace(data);
    renderDerivation(data);
  } catch (err) {
    setVerdict(false, "Request failed", String(err));
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyze";
  }
}

function setVerdict(accepted, text, reason) {
  const box = $("verdict");
  box.className = "verdict " +
    (accepted === null ? "idle" : accepted ? "accepted" : "rejected");
  $("verdict-mark").textContent =
    accepted === null ? "" : accepted ? "\u2713" : "\u2717";
  $("verdict-text").textContent = text;
  $("verdict-reason").textContent = reason || "";
  if (accepted === null) $("verdict-counts").innerHTML = "";
  // Re-trigger the fade so repeated analyses are visibly acknowledged.
  box.style.animation = "none";
  void box.offsetWidth;
  box.style.animation = "";
}

function renderCounts(d) {
  const box = $("verdict-counts");
  box.innerHTML = "";
  const slang = d.tokens.filter((t) => t.slang).length;
  [[d.tokens.length, "tokens"],
   [slang, "slang"],
   [d.trace.length, "steps"]].forEach(([n, label]) => {
    const c = el("div", "vc");
    c.appendChild(el("b", null, n));
    c.appendChild(el("span", null, label));
    box.appendChild(c);
  });
}

/* ====================================================================
   Renderers
   ==================================================================== */

function table(target, headers, rows) {
  const t = $(target);
  t.innerHTML = "";

  const thead = el("thead");
  const hr = el("tr");
  headers.forEach((h) => hr.appendChild(el("th", null, h)));
  thead.appendChild(hr);
  t.appendChild(thead);

  const tbody = el("tbody");
  rows.forEach((row) => tbody.appendChild(row));
  t.appendChild(tbody);
  return tbody;
}

function td(content, cls) {
  const c = el("td", cls);
  if (content instanceof Node) c.appendChild(content);
  else c.textContent = content === null || content === undefined ? "" : String(content);
  return c;
}

function renderTokens(d) {
  const rows = d.tokens.map((t) => {
    const tr = el("tr", t.type === "UNKNOWN" ? "bad" : null);
    tr.appendChild(td(t.i, "num"));
    tr.appendChild(td(t.lexeme, "lex"));
    tr.appendChild(td(el("span", "badge t-" + t.type, t.type)));

    const langs = el("span");
    t.languages.forEach((l) => langs.appendChild(el("span", "lang", l)));
    tr.appendChild(td(langs));

    tr.appendChild(td(t.slang ? el("span", "star", "\u2605") : ""));
    tr.appendChild(td(t.rule, "muted"));
    tr.appendChild(td(t.gloss));
    return tr;
  });

  table("tokens-table",
        ["#", "Lexeme", "Token", "Language", "Slang", "Rule", "Gloss"],
        rows);

  // Lexical errors are appended so an unknown word is never silently lost.
  if (d.lexErrors.length) {
    const tbody = $("tokens-table").querySelector("tbody");
    d.lexErrors.forEach((e) => {
      const tr = el("tr", "bad");
      const c = td(`line ${e.line}, col ${e.column}: "${e.lexeme}" \u2014 ${e.message}`);
      c.colSpan = 7;
      tr.appendChild(c);
      tbody.appendChild(tr);
    });
  }
}

function renderTree(d) {
  const host = $("tree");
  host.innerHTML = "";
  if (!d.tree) {
    host.appendChild(el("p", "empty",
      "No parse tree \u2014 the statement was rejected. " + (d.reason || "")));
    return;
  }
  const root = el("div", "tree-root");
  root.appendChild(nodeView(d.tree));
  host.appendChild(root);
}

function nodeView(node) {
  const kids = node.children || [];
  const box = el("div", "node" + (kids.length ? " has-kids" : ""));

  const row = el("div", "node-row");
  row.appendChild(el("span", "fold", kids.length ? "\u25BE" : ""));

  const cls = node.epsilon ? "sym eps" : node.terminal ? "sym term" : "sym";
  row.appendChild(el("span", cls, node.symbol));
  if (node.lexeme !== null && node.lexeme !== undefined) {
    row.appendChild(el("span", "leaf-lex", node.lexeme));
  }
  if (kids.length) {
    row.appendChild(el("span", "kid-count",
      kids.length === 1 ? "1 child" : kids.length + " children"));
  }
  box.appendChild(row);

  if (kids.length) {
    const holder = el("div", "kids");
    kids.forEach((k) => holder.appendChild(nodeView(k)));
    box.appendChild(holder);
    row.onclick = (ev) => { ev.stopPropagation(); box.classList.toggle("folded"); };
  }
  return box;
}

function renderTrace(d) {
  const rows = d.trace.map((s) => {
    const tr = el("tr");
    tr.appendChild(td(s.number, "num"));
    tr.appendChild(td(s.stack));
    tr.appendChild(td(s.remaining));
    tr.appendChild(td(s.action));
    return tr;
  });
  table("trace-table", ["Step", "Stack", "Remaining input", "Action"], rows);
}

function renderDerivation(d) {
  const list = $("deriv");
  list.innerHTML = "";
  if (!d.derivation.length) {
    const li = el("li", null, "No derivation \u2014 the statement was rejected.");
    li.style.paddingLeft = "0";
    list.appendChild(li);
    return;
  }
  d.derivation.forEach((form) => list.appendChild(el("li", null, form)));
}

function renderSets() {
  const rows = BOOT.sets.map((s) => {
    const tr = el("tr");
    tr.appendChild(td(el("span", "badge t-NOUN", s.nt)));
    tr.appendChild(td(chips(s.first)));
    tr.appendChild(td(chips(s.follow)));
    return tr;
  });
  table("sets-table", ["Nonterminal", "FIRST", "FOLLOW"], rows);
}

function chips(items) {
  const box = el("span");
  items.forEach((i) => box.appendChild(el("span", "set-chip", i)));
  return box;
}

function renderCorpus() {
  const rows = BOOT.corpus.map((r) => {
    const tr = el("tr", (r.accepted ? "good" : "bad") + " clickable");
    tr.title = "Click to load into the analyzer";
    tr.onclick = () => {
      $("entry").value = r.text;
      analyze();
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    tr.appendChild(td(r.sid, "num"));
    tr.appendChild(td(el("span", "badge " + (r.accepted ? "ok-badge" : "bad-badge"),
                         r.verdict)));
    tr.appendChild(td(r.topic, "muted"));
    tr.appendChild(td(r.text, "lex"));
    tr.appendChild(td(r.reason || r.gloss, "muted"));
    return tr;
  });
  table("corpus-table",
        ["ID", "Verdict", "Topic", "Transcription", "Reason / gloss"], rows);
}

function renderStats() {
  const s = BOOT.stats;
  const host = $("stats");
  host.innerHTML = "";

  const cards = el("div", "stat-cards");
  const card = (n, label, cls) => {
    const c = el("div", "stat-card" + (cls ? " " + cls : ""));
    c.appendChild(el("b", null, n));
    c.appendChild(el("span", null, label));
    return c;
  };
  cards.appendChild(card(s.statements, "statements"));
  cards.appendChild(card(s.accepted, "accepted", "good"));
  cards.appendChild(card(s.rejected, "rejected", "bad"));
  cards.appendChild(card(s.totalTokens, "tokens"));
  cards.appendChild(card(s.distinctLexemes, "distinct lexemes"));
  cards.appendChild(card(s.typeTokenRatio.toFixed(2), "type / token"));
  cards.appendChild(card(s.slangTokens, "slang tokens"));
  cards.appendChild(card(s.multiword, "multiword"));
  host.appendChild(cards);

  host.appendChild(barBlock("Token types", s.types, ""));
  host.appendChild(barBlock("Source languages", s.languages, "lang"));

  const g = BOOT.grammar;
  const unreviewed = g.unreviewed || 0;
  const grammarBlock = el("div", "stat-block");
  grammarBlock.appendChild(el("h3", null, "Grammar"));
  const gcards = el("div", "stat-cards");
  gcards.appendChild(card(g.nonterminals, "nonterminals"));
  gcards.appendChild(card(g.terminals, "terminals"));
  gcards.appendChild(card(g.cells, "filled cells"));
  // A reviewed conflict is a decision, not a fault, so it is only marked
  // red when nobody has accounted for it.
  gcards.appendChild(card(unreviewed, "unreviewed conflicts",
                          unreviewed ? "bad" : "good"));
  grammarBlock.appendChild(gcards);
  host.appendChild(grammarBlock);

  if (g.conflicts.length) host.appendChild(conflictBlock(g.conflicts));

  if (s.variants.length) {
    const block = el("div", "stat-block");
    block.appendChild(el("h3", null, "Spelling variation"));
    const bars = el("div", "bars");
    s.variants.forEach((v) => {
      const row = el("div", "bar-row");
      row.appendChild(el("div", "name", v.normalized));
      const spell = el("div", null, v.spellings);
      spell.style.fontFamily = "var(--mono)";
      spell.style.fontSize = "11.5px";
      spell.style.color = "var(--slate)";
      row.appendChild(spell);
      row.appendChild(el("div", "val", v.total + "\u00d7"));
      bars.appendChild(row);
    });
    block.appendChild(bars);
    host.appendChild(block);
  }
}

/**
 * Conflicts, explained.
 *
 * A cell holding two productions is only a *defect* if nobody has accounted
 * for it.  The one conflict this grammar has is the noun-compounding
 * ambiguity, resolved greedily on purpose and argued for in the report, so it
 * is presented as the decision it is rather than as a failure.
 */
function conflictBlock(conflicts) {
  const block = el("div", "stat-block");
  block.appendChild(el("h3", null, "Parse table conflicts"));

  const lead = el("p", "block-lead",
    "A conflict means two productions compete for one cell, so one token of " +
    "lookahead does not settle the parser's next move. Each is resolved by a " +
    "stated rule, in the way the dangling-else ambiguity is conventionally " +
    "resolved in favour of the nearest if.");
  block.appendChild(lead);

  conflicts.forEach((c) => {
    const item = el("div", "conflict" + (c.documented ? " resolved" : " open"));

    const head = el("div", "conflict-head");
    head.appendChild(el("span", "badge " + (c.documented ? "ok-badge" : "bad-badge"),
                        c.documented ? "RESOLVED" : "UNREVIEWED"));
    head.appendChild(el("code", "cell", `M[${c.nonterminal}, ${c.terminal}]`));
    item.appendChild(head);

    const rules = el("div", "conflict-rules");
    const keep = el("div", "rule-line keep");
    keep.appendChild(el("span", "rule-tag", "taken"));
    keep.appendChild(el("code", null, c.chosen));
    rules.appendChild(keep);

    const drop = el("div", "rule-line drop");
    drop.appendChild(el("span", "rule-tag", "not taken"));
    drop.appendChild(el("code", null, c.rejected));
    rules.appendChild(drop);
    item.appendChild(rules);

    item.appendChild(el("p", "conflict-note",
      c.note || "This conflict has not been reviewed. It is a defect and " +
                "should be resolved before submission."));

    block.appendChild(item);
  });

  return block;
}

function barBlock(title, items, extraClass) {  const block = el("div", "stat-block");
  block.appendChild(el("h3", null, title));
  const bars = el("div", "bars");
  const max = Math.max(...items.map((i) => i.share), 1);

  items.forEach((item, idx) => {
    const row = el("div", "bar-row" + (extraClass ? " " + extraClass : ""));
    row.appendChild(el("div", "name", item.name));

    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    track.appendChild(fill);
    row.appendChild(track);

    row.appendChild(el("div", "val", `${item.count}  \u00b7  ${item.share}%`));
    bars.appendChild(row);

    // Staggered so the chart draws itself rather than snapping into place.
    setTimeout(() => { fill.style.width = (100 * item.share / max) + "%"; },
               60 + idx * 28);
  });

  block.appendChild(bars);
  return block;
}

/* ====================================================================
   Tabs
   ==================================================================== */

function positionInk() {
  const active = document.querySelector(".tab.active");
  const ink = $("tab-ink");
  if (!active || !ink) return;
  ink.style.left  = active.offsetLeft + "px";
  ink.style.width = active.offsetWidth + "px";
}

function wireTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $(tab.dataset.panel).classList.add("active");
      positionInk();
    };
  });
  window.addEventListener("resize", positionInk);
}

/* ====================================================================
   Wiring
   ==================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  wireTabs();

  $("run").onclick = analyze;
  $("entry").addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyze();
  });
  $("clear").onclick = () => {
    $("entry").value = "";
    $("entry").focus();
    setVerdict(null, "Type a statement and press Analyze.", "");
  };

  boot();
});
