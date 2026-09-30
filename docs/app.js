var $ = function (id) { return document.getElementById(id); };
var state = { q: "", mode: "best", ids: [], shown: 0 };
var lib = { cards: [], index: null, files: {}, config: {}, vectors: null, rowToDoc: null, extractor: null, semState: "idle" };
var PAGE = 20;

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function getJson(url) {
  return fetch(url, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(url + " " + r.status); return r.json(); });
}

// ---- pages
function show() {
  var libv = location.hash === "#library";
  $("view-search").style.display = libv ? "none" : "";
  $("view-library").style.display = libv ? "" : "none";
}
window.addEventListener("hashchange", show);

function setLinks() {
  var repo = lib.config.repo, branch = lib.config.branch;
  if (!repo) return;
  var up = "https://github.com/" + repo + "/upload/" + branch + "/incoming";
  $("add-link").href = up; $("add-link2").href = up;
  $("folder-link").href = "https://github.com/" + repo + "/tree/" + branch + "/incoming";
}

// ---- rendering. runs are [text, tier]: 2 highlighted (spoken), 1 underlined/bold context, 0 plain
function runsHtml(runs, forCopy) {
  return runs.map(function (r) {
    var t = esc(r[0]);
    if (r[1] === 2) return forCopy ? '<span style="background-color:#ffff00;font-weight:bold;text-decoration:underline">' + t + "</span>" : "<mark>" + t + "</mark>";
    if (r[1] === 1) return forCopy ? '<span style="font-weight:bold;text-decoration:underline">' + t + "</span>" : '<span class="ctx">' + t + "</span>";
    return forCopy ? t : '<span class="plain">' + t + "</span>";
  }).join("");
}
function citeHtml(c) {
  if (!c.cite_runs) return esc(c.cite);
  return c.cite_runs.map(function (r) { return r[1] ? "<b>" + esc(r[0]) + "</b>" : esc(r[0]); }).join("");
}
function sourceLinks(c) {
  var repo = lib.config.repo, branch = lib.config.branch;
  return c.src.map(function (sha) {
    var f = lib.files[sha]; if (!f) return "";
    return repo ? '<a href="https://github.com/' + repo + "/blob/" + branch + "/incoming/" + encodeURI(f.name) + '" target="_blank">' + esc(f.name) + "</a>" : esc(f.name);
  }).filter(Boolean).join(", ");
}
function cardHtml(c) {
  var flag = c.method === "heuristic" ? " | tag guessed from layout" : "";
  if (!c.cite_ok) flag += " | cite not recognized";
  return '<div class="card" id="card-' + c.id + '">' +
    '<div class="tag">' + (c.tag ? esc(c.tag) : '<span class="plain">(no tag in file)</span>') + "</div>" +
    '<div class="cite">' + esc(c.cite) + "</div>" +
    '<div class="spoken">' + (c.spoken ? "<mark>" + esc(c.spoken) + "</mark>" : '<span class="plain">(no highlighted text)</span>') + "</div>" +
    '<div class="body" id="body-' + c.id + '"></div>' +
    '<div class="actions"><button data-act="full" data-id="' + c.id + '">Show full card</button>' +
    '<button data-act="copy" data-id="' + c.id + '">Copy</button></div>' +
    '<div class="meta">In: ' + sourceLinks(c) + esc(flag) + "</div></div>";
}

// ---- search
function embedQuery(q) {
  if (lib.extractor) return Promise.resolve(lib.extractor);
  if (lib.semState === "failed") return Promise.reject(new Error("unavailable"));
  lib.semState = "loading"; $("summary").textContent = "Loading the meaning-search model (first time only, this can take a minute)...";
  return import("https://cdn.jsdelivr.net/npm/@huggingface/transformers@3").then(function (m) {
    return m.pipeline("feature-extraction", lib.config.model || "Xenova/bge-small-en-v1.5");
  }).then(function (p) { lib.extractor = p; lib.semState = "ready"; return p; })
    .catch(function (e) { lib.semState = "failed"; throw e; });
}
function loadVectors() {
  if (lib.vectors) return Promise.resolve();
  return Promise.all([fetch("data/embeddings.bin").then(function (r) { if (!r.ok) throw new Error("no vectors"); return r.arrayBuffer(); }), getJson("data/embeddings.ids.json")])
    .then(function (res) {
      var idToIdx = {}; lib.cards.forEach(function (c, i) { idToIdx[c.id] = i; });
      lib.vectors = new Int8Array(res[0]);
      lib.rowToDoc = res[1].map(function (id) { return idToIdx[id]; });
    });
}
function meaningRanking(q) {
  return Promise.all([loadVectors(), embedQuery(q)]).then(function (r) {
    var prefix = "Represent this sentence for searching relevant passages: ";
    return r[1](prefix + q, { pooling: "cls", normalize: true });
  }).then(function (out) {
    return CardSearch.semantic(lib.vectors, 384, lib.rowToDoc, out.data, 200);
  });
}
function runSearch() {
  var q = state.q, mode = state.mode;
  $("results").innerHTML = ""; $("more").style.display = "none";
  var kw = mode === "meaning" ? [] : lib.index.keyword(q, 200);
  var finish = function (ids, note) {
    state.ids = ids; state.shown = 0;
    $("summary").textContent = ids.length ? ids.length + " cards found" + (note || "") : "No cards found." + (note || "");
    more();
  };
  if (mode === "keyword") return finish(kw);
  meaningRanking(q).then(function (sem) {
    finish(mode === "meaning" ? sem : CardSearch.fuse([kw, sem]));
  }).catch(function () {
    finish(mode === "meaning" ? [] : kw, mode === "meaning" ? " (meaning search is unavailable in this browser or network)" : " (exact words only; meaning search unavailable)");
  });
}
function more() {
  var slice = state.ids.slice(state.shown, state.shown + PAGE);
  $("results").insertAdjacentHTML("beforeend", slice.map(function (i) { return cardHtml(lib.cards[i]); }).join(""));
  state.shown += slice.length;
  $("more").style.display = state.shown < state.ids.length ? "" : "none";
}
$("search-form").addEventListener("submit", function (e) {
  e.preventDefault();
  state.q = $("q").value.trim();
  if (!state.q || !lib.index) return;
  state.mode = document.querySelector('input[name="mode"]:checked').value;
  runSearch();
});
$("more").addEventListener("click", more);

var cache = {};
function getCard(id) {
  if (cache[id]) return Promise.resolve(cache[id]);
  var base = lib.cards.filter(function (c) { return String(c.id) === String(id); })[0];
  return getJson("data/c/" + id + ".json").then(function (d) { var c = Object.assign({}, base, d); cache[id] = c; return c; });
}
$("results").addEventListener("click", function (e) {
  var b = e.target.closest("button");
  if (!b) return;
  var id = b.getAttribute("data-id");
  if (b.getAttribute("data-act") === "full") {
    var box = $("body-" + id);
    if (box.innerHTML) { box.innerHTML = ""; b.textContent = "Show full card"; return; }
    getCard(id).then(function (c) {
      box.innerHTML = '<div class="cite">' + citeHtml(c) + "</div>" + c.body.map(function (p) { return "<p>" + runsHtml(p, false) + "</p>"; }).join("");
      b.textContent = "Hide full card";
    });
  } else {
    getCard(id).then(function (c) { copyCard(c, b); });
  }
});
function copyCard(c, btn) {
  var html = (c.tag ? "<h4>" + esc(c.tag) + "</h4>" : "") + "<p>" + citeHtml(c) + "</p>" +
    c.body.map(function (p) { return "<p>" + runsHtml(p, true) + "</p>"; }).join("");
  var text = (c.tag ? c.tag + "\n" : "") + c.cite + "\n\n" + c.body.map(function (p) { return p.map(function (r) { return r[0]; }).join(""); }).join("\n\n");
  var done = function () { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy"; }, 1500); };
  if (navigator.clipboard && window.ClipboardItem) {
    navigator.clipboard.write([new ClipboardItem({
      "text/html": new Blob([html], { type: "text/html" }),
      "text/plain": new Blob([text], { type: "text/plain" })
    })]).then(done, function () { btn.textContent = "Copy failed"; });
  } else {
    navigator.clipboard.writeText(text).then(done);
  }
}

// ---- library list
function showLibrary() {
  var rows = Object.keys(lib.files).map(function (sha) { return lib.files[sha]; })
    .sort(function (a, b) { return a.name.localeCompare(b.name); });
  $("docs").innerHTML = rows.length ? "<table><tr><th>File</th><th>Cards</th></tr>" + rows.map(function (f) {
    return "<tr><td>" + esc(f.name) + (f.error ? ' <span class="warn">(could not read: ' + esc(f.error) + ")</span>" : "") + "</td><td>" + f.n_cards + "</td></tr>";
  }).join("") + "</table>" : "No files yet.";
}

// ---- start
getJson("config.json").catch(function () { return {}; }).then(function (cfg) {
  lib.config = cfg; setLinks();
  return Promise.all([getJson("data/index.json"), getJson("data/files.json")]);
}).then(function (r) {
  lib.cards = r[0].cards; lib.files = r[1];
  lib.index = new CardSearch.Index(lib.cards);
  $("status").textContent = lib.cards.length + " cards from " + Object.keys(lib.files).length + " files";
  showLibrary(); show();
}).catch(function () { $("status").textContent = "No cards yet. Add files (see Library)."; show(); });
show();
