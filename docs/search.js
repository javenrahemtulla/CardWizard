/* Card Wizard search engine, runs entirely in the browser.
 * Keyword: BM25 over four weighted fields. Meaning: cosine similarity against precomputed vectors.
 * Works in browsers and in Node (for tests): CardSearch is attached to `self` or `module.exports`. */
(function (root) {
  var STOP = new Set(("a an and are as at be but by for from has have how i if in into is it its of on or our so than that the their " +
    "them then there these they this to us was we what when where which who why will with you your about can does do not").split(" "));
  var FIELDS = [["tag", 8], ["cite", 3], ["spoken", 6], ["context", 2]];
  var K1 = 1.2, B = 0.75;

  function stem(w) {
    if (w.length <= 3) return w;
    if (w.endsWith("ies") && w.length > 4) return w.slice(0, -3) + "y";
    if (w.endsWith("ations")) return w.slice(0, -6);
    if (w.endsWith("ation")) return w.slice(0, -5);
    if (w.endsWith("ings") && w.length > 6) return w.slice(0, -4);
    if (w.endsWith("ing") && w.length > 5) return w.slice(0, -3);
    if (w.endsWith("ed") && w.length > 4) return w.slice(0, -2);
    if (w.endsWith("es") && w.length > 4) return w.slice(0, -2);
    if (w.endsWith("ly") && w.length > 4) return w.slice(0, -2);
    if (w.endsWith("s") && !w.endsWith("ss")) return w.slice(0, -1);
    return w;
  }

  function tokens(text, dropStop) {
    var out = [];
    var words = String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().match(/[a-z0-9]+/g) || [];
    for (var i = 0; i < words.length; i++) {
      if (dropStop && STOP.has(words[i])) continue;
      out.push(stem(words[i]));
    }
    return out;
  }

  function Index(cards) {
    this.cards = cards;
    this.n = cards.length;
    this.postings = new Map(); // term -> [[docIdx, tf per field...], ...]
    this.len = FIELDS.map(function () { return new Float64Array(cards.length); });
    this.avg = FIELDS.map(function () { return 1; });
    var sums = FIELDS.map(function () { return 0; });
    for (var d = 0; d < cards.length; d++) {
      for (var f = 0; f < FIELDS.length; f++) {
        var toks = tokens(cards[d][FIELDS[f][0]], false);
        this.len[f][d] = toks.length;
        sums[f] += toks.length;
        var tf = new Map();
        for (var t = 0; t < toks.length; t++) tf.set(toks[t], (tf.get(toks[t]) || 0) + 1);
        tf.forEach(function (count, term) {
          var list = this.postings.get(term);
          if (!list) { list = []; this.postings.set(term, list); }
          var last = list[list.length - 1];
          if (last && last[0] === d) last[1 + f] = count;
          else { var row = [d, 0, 0, 0, 0]; row[1 + f] = count; list.push(row); }
        }, this);
      }
    }
    for (var g = 0; g < FIELDS.length; g++) this.avg[g] = Math.max(1, sums[g] / Math.max(1, cards.length));
  }

  Index.prototype.keyword = function (query, limit) {
    var phrases = [];
    var rest = String(query).replace(/"([^"]+)"/g, function (_, p) { phrases.push(p.toLowerCase()); return " "; });
    var terms = Array.from(new Set(tokens(rest, true)));
    phrases.forEach(function (p) { tokens(p, false).forEach(function (t) { if (terms.indexOf(t) < 0) terms.push(t); }); });
    var scores = new Map();
    for (var i = 0; i < terms.length; i++) {
      var list = this.postings.get(terms[i]);
      if (!list) continue;
      var idf = Math.log(1 + (this.n - list.length + 0.5) / (list.length + 0.5));
      for (var k = 0; k < list.length; k++) {
        var row = list[k], d = row[0], s = 0;
        for (var f = 0; f < FIELDS.length; f++) {
          var tf = row[1 + f];
          if (!tf) continue;
          var norm = tf * (K1 + 1) / (tf + K1 * (1 - B + B * this.len[f][d] / this.avg[f]));
          s += FIELDS[f][1] * norm;
        }
        scores.set(d, (scores.get(d) || 0) + idf * s);
      }
    }
    if (phrases.length) {
      var self = this;
      scores.forEach(function (s, d) {
        var c = self.cards[d];
        var hay = (c.tag + " " + c.cite + " " + c.spoken + " " + c.context).toLowerCase();
        phrases.forEach(function (p) { if (hay.indexOf(p) >= 0) scores.set(d, scores.get(d) * 3); });
      });
    }
    return Array.from(scores.entries()).sort(function (a, b) { return b[1] - a[1]; }).slice(0, limit || 200).map(function (e) { return e[0]; });
  };

  // vectors: Int8Array of n*dim (row order = cards order given by `rowToDoc`), queryVec: Float32Array (normalised)
  function semantic(vectors, dim, rowToDoc, queryVec, limit) {
    var n = rowToDoc.length, sims = new Float32Array(n);
    for (var r = 0; r < n; r++) {
      var s = 0, base = r * dim;
      for (var j = 0; j < dim; j++) s += vectors[base + j] * queryVec[j];
      sims[r] = s / 127;
    }
    var order = Array.from(sims.keys()).sort(function (a, b) { return sims[b] - sims[a]; }).slice(0, limit || 200);
    return order.filter(function (r) { return sims[r] > 0.2; }).map(function (r) { return rowToDoc[r]; });
  }

  function fuse(rankings, k) {
    k = k || 60;
    var scores = new Map();
    rankings.forEach(function (ranking) {
      ranking.forEach(function (d, rank) { scores.set(d, (scores.get(d) || 0) + 1 / (k + rank)); });
    });
    return Array.from(scores.entries()).sort(function (a, b) { return b[1] - a[1]; }).map(function (e) { return e[0]; });
  }

  var api = { Index: Index, semantic: semantic, fuse: fuse, tokens: tokens };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CardSearch = api;
})(typeof self !== "undefined" ? self : this);
