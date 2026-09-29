var $ = function (id) { return document.getElementById(id); };
var state = { q: "", mode: "best", offset: 0, total: 0 };

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ---- pages
function show() {
  var add = location.hash === "#add";
  $("view-search").style.display = add ? "none" : "";
  $("view-add").style.display = add ? "" : "none";
  if (add) loadDocs();
}
window.addEventListener("hashchange", show);

function loadStatus() {
  fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
    var t = s.cards + " cards from " + s.documents + " files";
    if (s.embedding_pending) t += ". Indexing " + s.embedding_pending + " cards for meaning search.";
    if (s.semantic === "disabled") t += ". Meaning search is off (" + (s.semantic_error || "model not loaded") + ").";
    $("status").textContent = t;
  });
}
setInterval(loadStatus, 5000);

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
  return c.cite_runs.map(function (r) {
    return r[1] ? "<b>" + esc(r[0]) + "</b>" : esc(r[0]);
  }).join("");
}

function cardHtml(c) {
  var src = c.sources.map(function (s) {
    return '<a href="/api/documents/' + s.doc_id + '/file">' + esc(s.filename) + "</a>";
  }).join(", ");
  var flag = c.method === "heuristic" ? " | tag guessed from layout" : "";
  if (!c.cite_ok) flag += " | cite not recognized";
  return '<div class="card" id="card-' + c.id + '">' +
    '<div class="tag">' + (c.tag ? esc(c.tag) : '<span class="plain">(no tag in file)</span>') + "</div>" +
    '<div class="cite">' + citeHtml(c) + "</div>" +
    '<div class="spoken">' + (c.spoken ? "<mark>" + esc(c.spoken) + "</mark>" : '<span class="plain">(no highlighted text)</span>') + "</div>" +
    '<div class="body" id="body-' + c.id + '"></div>' +
    '<div class="actions"><button data-act="full" data-id="' + c.id + '">Show full card</button>' +
    '<button data-act="copy" data-id="' + c.id + '">Copy</button></div>' +
    '<div class="meta">In: ' + src + esc(flag) + "</div></div>";
}

// ---- search
function runSearch(more) {
  if (!more) { state.offset = 0; $("results").innerHTML = ""; }
  var url = "/api/search?q=" + encodeURIComponent(state.q) + "&mode=" + state.mode + "&offset=" + state.offset + "&limit=20";
  fetch(url).then(function (r) { return r.json(); }).then(function (j) {
    state.total = j.total;
    if (!more && !j.cards.length) $("summary").textContent = "No cards found.";
    else $("summary").textContent = j.total + " cards found" + (j.semantic === "disabled" && state.mode !== "keyword" ? " (exact words only; meaning search is off)" : "");
    $("results").insertAdjacentHTML("beforeend", j.cards.map(cardHtml).join(""));
    state.offset += j.cards.length;
    $("more").style.display = state.offset < state.total ? "" : "none";
  });
}

$("search-form").addEventListener("submit", function (e) {
  e.preventDefault();
  state.q = $("q").value.trim();
  if (!state.q) return;
  state.mode = document.querySelector('input[name="mode"]:checked').value;
  runSearch(false);
});
$("more").addEventListener("click", function () { runSearch(true); });

var cache = {};
function getCard(id) {
  if (cache[id]) return Promise.resolve(cache[id]);
  return fetch("/api/cards/" + id).then(function (r) { return r.json(); }).then(function (c) { cache[id] = c; return c; });
}

$("results").addEventListener("click", function (e) {
  var b = e.target.closest("button");
  if (!b) return;
  var id = b.getAttribute("data-id");
  if (b.getAttribute("data-act") === "full") {
    var box = $("body-" + id);
    if (box.innerHTML) { box.innerHTML = ""; b.textContent = "Show full card"; return; }
    getCard(id).then(function (c) {
      box.innerHTML = c.body.map(function (p) { return "<p>" + runsHtml(p, false) + "</p>"; }).join("");
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

// ---- add files
function showResults(res) {
  $("upload-out").innerHTML = res.results.map(function (r) {
    if (r.error) return '<p class="warn">' + esc(r.filename) + ": " + esc(r.error) + "</p>";
    var s = "<p>" + esc(r.filename) + ": " + r.cards + " cards found, " + r.new + " new, " + r.duplicates + " already in library.";
    (r.warnings || []).forEach(function (w) { s += '<br><span class="warn">' + esc(w) + "</span>"; });
    return s + "</p>";
  }).join("");
  loadDocs(); loadStatus();
}

$("upload").addEventListener("click", function () {
  var f = $("files").files;
  if (!f.length) return;
  var fd = new FormData();
  for (var i = 0; i < f.length; i++) fd.append("files", f[i]);
  $("upload-out").textContent = "Uploading...";
  fetch("/api/upload", { method: "POST", body: fd }).then(function (r) { return r.json(); }).then(showResults)
    .catch(function () { $("upload-out").textContent = "Upload failed."; });
  $("files").value = "";
});

$("paste-go").addEventListener("click", function () {
  var box = $("paste-box");
  var body = { html: box.innerHTML, text: box.innerText, name: $("paste-name").value };
  $("upload-out").textContent = "Adding...";
  fetch("/api/paste", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then(function (r) { return r.json(); }).then(function (j) { box.innerHTML = ""; showResults(j); });
});

function loadDocs() {
  fetch("/api/documents").then(function (r) { return r.json(); }).then(function (docs) {
    if (!docs.length) { $("docs").textContent = "No files yet."; return; }
    $("docs").innerHTML = "<table><tr><th>File</th><th>Cards</th><th>Added</th><th></th></tr>" + docs.map(function (d) {
      return "<tr><td><a href='/api/documents/" + d.id + "/file'>" + esc(d.filename) + "</a></td><td>" + d.n_cards + "</td><td>" +
        new Date(d.uploaded_at * 1000).toLocaleDateString() + "</td><td><button data-del='" + d.id + "'>Delete</button></td></tr>";
    }).join("") + "</table>";
  });
}
$("docs").addEventListener("click", function (e) {
  var id = e.target.getAttribute("data-del");
  if (id && confirm("Delete this file and any cards only it contains?")) {
    fetch("/api/documents/" + id, { method: "DELETE" }).then(function () { loadDocs(); loadStatus(); });
  }
});

show();
loadStatus();
