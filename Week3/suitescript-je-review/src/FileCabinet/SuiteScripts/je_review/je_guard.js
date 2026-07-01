/**
 * je_guard.js  -  THE AUDIT SEAM (ported from je_review.guard_note in Week3/je_review.py).
 *
 * A deterministic check over the AI reviewer note: every material figure it mentions must trace to
 * the entry's own facts (its amount, its risk score, its flag count) or to an identifier that
 * legitimately carries digits (the account code, the JE id). A model that invents an exposure figure
 * is caught here before the note can reach the worklist. This is the piece the native N/llm route
 * does NOT give you — it is what keeps "AI drafts, code checks, human approves" auditable.
 *
 * Returns { ok, offenders }.
 *
 * @NApiVersion 2.1
 */
define([], function () {

  var NUM_RE = /[-+]?\d[\d,]*(?:\.\d+)?/g;

  /** Figures a reviewer note may mention: the entry's facts + identifiers that carry digits. */
  function allowedNumbers(assessment) {
    var je = assessment.je;
    var set = {};
    add(set, Math.round(Number(je.amount) * 100) / 100);
    add(set, Number(assessment.risk_score));
    add(set, (assessment.flags || []).length);
    // account code + je id digits are identifiers, not invented figures
    var idText = String(je.account || '') + ' ' + String(je.je_id || '');
    (idText.match(/\d+/g) || []).forEach(function (tok) { add(set, parseFloat(tok)); });
    return set;
  }

  function add(set, v) { var x = parseFloat(v); if (!isNaN(x)) set[x] = true; }

  /**
   * True if every material figure in the note traces to an allowed value. Small numbers (< 1000) are
   * treated as ordinals/counts and not policed as money; material figures must match within moneyTol.
   */
  function guardNote(note, assessment, moneyTol) {
    moneyTol = (moneyTol == null) ? 1.0 : moneyTol;
    var allowed = allowedNumbers(assessment);
    var allowedList = Object.keys(allowed).map(parseFloat);
    var text = String(note && note.note != null ? note.note : note || '');
    var offenders = [], m;
    NUM_RE.lastIndex = 0;
    while ((m = NUM_RE.exec(text)) !== null) {
      var val = parseFloat(m[0].replace(/,/g, ''));
      if (isNaN(val)) continue;
      if (val < 1000) continue;                       // ordinals / counts / small scores — not money
      var ok = allowedList.some(function (a) { return Math.abs(val - a) <= moneyTol; });
      if (!ok) offenders.push(m[0]);
    }
    return { ok: offenders.length === 0, offenders: offenders };
  }

  return { allowedNumbers: allowedNumbers, guardNote: guardNote };
});
