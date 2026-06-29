/**
 * flux_eval.js  -  THE AUDIT SEAM (ported from eval_check.py + ns_flux_eval.py).
 *
 * Two deterministic checks guard every AI narrative before it can reach the report:
 *   1. NUMBER-MATCH (hard): every figure must trace to the account facts, a pulled driver amount, or
 *      a code-computed extra fact (trend/SPLY/vendor-bridge delta).
 *   2. ENTITY PROVENANCE (heuristic allowlist): only vendors present in the drivers may be named.
 * Cited transaction references (tranids, journal ids, bill names, memos) are stripped before the
 * number check so the narrative may quote its source without the digits reading as invented figures.
 *
 * This is the piece the native N/llm path does NOT give you - it is what makes "AI drafts, code
 * checks, human approves" auditable. Returns { ok, bad_numbers, bad_entities }.
 *
 * @NApiVersion 2.1
 */
define([], function () {

  var NUM_RE = /[-+]?\d[\d,. ]*\d\s*%?|\d+%?/g;
  var COMPANY_RE = /[A-Z][\w&.\-]*(?:\s+[A-Z0-9][\w&.\-]*)*\s+(?:AB|B\.?V\.?|Ltd|Limited|GmbH|SAS|S\.?R\.?L\.?|Inc|LLC|Oy|AG|SE|S\.?A\.?)\b/g;
  var MONTHS = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December';
  var DATE_RES = [
    new RegExp('\\b\\d{1,2}\\s+(?:' + MONTHS + ')\\b', 'gi'),
    new RegExp('\\b(?:' + MONTHS + ')\\s+\\d{1,2}\\b', 'gi'),
    new RegExp('\\b(?:' + MONTHS + ')\\s+\\d{4}\\b', 'gi'),
    /\b\d{4}-\d{2}-\d{2}\b/g,
    /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/g,
    /\b\d{1,2}\.\d{1,2}\.\d{2,4}\b/g,   // dotted dd.mm.yyyy (NetSuite memos)
    /\b(?:19|20)\d{2}\b/g               // a bare calendar year is a date, not a financial figure
  ];

  function normalise(token) {
    var t = String(token).replace(/\s/g, '');
    var isPct = t.charAt(t.length - 1) === '%';
    t = t.replace(/[^\d.\-]/g, '');
    if (t === '' || t === '-' || t === '.' || t === '-.') return null;
    var val = parseFloat(t);
    if (isNaN(val)) return null;
    return isPct ? val / 100 : val;
  }

  function extractNumbers(text) {
    var found = [], m;
    NUM_RE.lastIndex = 0;
    while ((m = NUM_RE.exec(text)) !== null) {
      var v = normalise(m[0]);
      if (v !== null) found.push({ token: m[0].trim(), value: v });
    }
    return found;
  }

  function stripDates(text) {
    DATE_RES.forEach(function (re) { text = text.replace(re, ' '); });
    return text;
  }

  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  function stripRefs(text, refs) {
    var clean = [];
    (refs || []).forEach(function (r) { var s = String(r == null ? '' : r).trim(); if (s) clean.push(s); });
    clean.sort(function (a, b) { return b.length - a.length; });  // longest first
    clean.forEach(function (ref) { text = text.replace(new RegExp(escapeRe(ref), 'gi'), ' '); });
    return text;
  }

  function addNumber(set, v) {
    var x = parseFloat(v);
    if (isNaN(x)) return;
    [Math.round(x * 100) / 100, Math.round(Math.abs(x) * 100) / 100,
     Math.round(x * 10000) / 10000, Math.round(Math.abs(x) * 10000) / 10000]
      .forEach(function (n) { set[n] = true; });
  }

  function allowedNumbers(fact, drivers, extraFacts) {
    var set = {};
    var prior = (fact.prior != null) ? fact.prior : fact.prior_amt;
    var current = (fact.current != null) ? fact.current : fact.current_amt;
    [prior, current, fact.variance_abs].forEach(function (v) {
      if (v != null) { addNumber(set, v); addNumber(set, Math.abs(parseFloat(v))); }
    });
    if (fact.variance_pct != null) addNumber(set, fact.variance_pct);
    (drivers || []).forEach(function (d) {
      if (d.amount != null) { addNumber(set, d.amount); addNumber(set, Math.abs(parseFloat(d.amount))); }
      if (d.lines != null) { var l = parseFloat(d.lines); if (!isNaN(l)) set[l] = true; }
    });
    if (extraFacts) {
      var vals = Array.isArray(extraFacts) ? extraFacts
        : Object.keys(extraFacts).map(function (k) { return extraFacts[k]; });
      vals.forEach(function (v) { addNumber(set, v); });
    }
    return set;
  }

  function allowedEntities(drivers, extra) {
    var set = {};
    (drivers || []).forEach(function (d) {
      if (d.entity) set[String(d.entity).trim().toLowerCase()] = true;
    });
    (extra || []).forEach(function (e) {
      if (e) set[String(e).trim().toLowerCase()] = true;       // e.g. the row's own subsidiary
    });
    return set;
  }

  /**
   * True only if every number traces to the facts/drivers/extra AND every company-like name is a
   * pulled vendor. money_tol/pct_tol absorb rounding. Returns { ok, bad_numbers, bad_entities }.
   */
  function checkExplanation(narrative, fact, drivers, opts) {
    opts = opts || {};
    var moneyTol = opts.money_tol != null ? opts.money_tol : 1.0;
    var pctTol = opts.pct_tol != null ? opts.pct_tol : 0.001;
    var allowed = allowedNumbers(fact, drivers, opts.extra_facts);
    var allowedList = Object.keys(allowed).map(parseFloat);
    var clean = stripRefs(stripDates(narrative), opts.allowed_refs);

    var badNumbers = [];
    extractNumbers(clean).forEach(function (n) {
      // Police MONETARY/percentage figures only. A bare 1-2 digit integer (no separator, no %) is a
      // date fragment / ordinal / small count, never a material amount here (amounts are >= the 25k
      // gate and comma/currency-formatted), so it is not treated as an invented figure.
      if (/^\d{1,2}$/.test(n.token.trim())) return;
      var tol = (n.token.charAt(n.token.length - 1) === '%') ? pctTol : moneyTol;
      var ok = allowedList.some(function (a) { return Math.abs(n.value - a) <= tol; });
      if (!ok) badNumbers.push(n.token);
    });

    var ents = allowedEntities(drivers, opts.extra_entities);
    var entKeys = Object.keys(ents);
    var badEntities = [], m;
    COMPANY_RE.lastIndex = 0;
    while ((m = COMPANY_RE.exec(narrative)) !== null) {
      var name = m[0].trim().toLowerCase();
      var ok2 = entKeys.some(function (e) { return name.indexOf(e) !== -1 || e.indexOf(name) !== -1; });
      if (!ok2) badEntities.push(m[0].trim());
    }
    return { ok: badNumbers.length === 0 && badEntities.length === 0, bad_numbers: badNumbers, bad_entities: badEntities };
  }

  return {
    extractNumbers: extractNumbers, stripDates: stripDates, stripRefs: stripRefs,
    allowedNumbers: allowedNumbers, allowedEntities: allowedEntities, checkExplanation: checkExplanation
  };
});
