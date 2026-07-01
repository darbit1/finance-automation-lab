/**
 * je_report.js  -  deterministic HTML worklist assembler (mirrors Week3/je_report.py).
 *
 * Numbers and dispositions come from the rules + the maker-checker result; the only AI text is each
 * guarded reviewer/challenger note. A note that failed the audit seam is shown with a warning and is
 * never relied upon. Ordered most-risky first so a controller works top-down.
 *
 * @NApiVersion 2.1
 */
define([], function () {

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function money(v, ccy) { return ccy + ' ' + (Math.round(Number(v) || 0)).toLocaleString('en-US'); }

  var TIER_RANK = { high: 0, medium: 1, low: 2, clear: 3 };
  var DISPOSITION = {
    escalate: { label: 'Escalate', color: '#b91c1c', bg: '#fef2f2' },
    monitor: { label: 'Monitor', color: '#92400e', bg: '#fffbeb' },
    accept: { label: 'Accept', color: '#166534', bg: '#f0fdf4' }
  };

  function buildEmail(meta, results) {
    var ccy = meta.currency;
    var n = results.length;
    var escalate = count(results, function (r) { return r.final_disposition === 'escalate'; });
    var monitor = count(results, function (r) { return r.final_disposition === 'monitor'; });
    var overrides = count(results, function (r) { return r.challenge.verdict !== 'agree'; });
    var guardFail = count(results, function (r) { return !r.note_guard_passed; });

    var ordered = results.slice().sort(function (a, b) {
      var d = TIER_RANK[a.assessment.tier] - TIER_RANK[b.assessment.tier];
      return d !== 0 ? d : b.assessment.risk_score - a.assessment.risk_score;
    });

    var H = [];
    H.push('<div style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;max-width:860px">');
    H.push('<h2 style="margin:0 0 2px">' + esc(meta.title) + '</h2>');
    H.push('<div style="color:#666;font-size:13px;margin-bottom:12px"><strong>' + esc(meta.period) +
      '</strong> &nbsp;|&nbsp; ' + n + ' manual journals assessed &nbsp;|&nbsp; generated ' + esc(meta.run_at) + '</div>');
    H.push('<p style="font-size:14px;margin:0 0 6px">' +
      '<strong style="color:#b91c1c">' + escalate + ' escalate</strong> &nbsp;·&nbsp; ' +
      '<strong style="color:#92400e">' + monitor + ' monitor</strong> &nbsp;·&nbsp; ' +
      (n - escalate - monitor) + ' accept. ' +
      'Four-eyes overrides: <strong>' + overrides + '</strong>. ' +
      'Audit-seam failures (AI note cited an untraceable figure): <strong>' + guardFail + '</strong>.</p>');
    H.push('<p style="font-size:13px;color:#444;margin:0 0 14px"><em>Flags are raised by deterministic ' +
      'SuiteScript rules; the reviewer/challenger notes are written by N/llm and code-checked. Code has ' +
      'the last word on disposition — a "missed risk" challenge forces escalation.</em></p>');

    var worklist = ordered.filter(function (r) { return r.assessment.tier === 'high' || r.assessment.tier === 'medium'; });
    worklist.forEach(function (r) { entryBlock(H, r, ccy); });

    var logged = ordered.filter(function (r) { return r.assessment.tier === 'low' || r.assessment.tier === 'clear'; });
    if (logged.length) {
      H.push('<h3 style="margin:18px 0 6px">Logged (no review required)</h3><ul style="font-size:13px;color:#444;margin:0 0 10px">');
      logged.forEach(function (r) {
        var je = r.assessment.je;
        H.push('<li>' + esc(je.je_id) + ' — ' + esc(je.account) + ', ' + money(je.amount, ccy) + ' ' +
          esc(je.dr_cr || '') + ' — score ' + r.assessment.risk_score +
          ' (' + esc(r.assessment.flag_rules.join(', ') || 'none') + ')</li>');
      });
      H.push('</ul>');
    }

    H.push('<hr style="border:none;border-top:1px solid #ddd;margin:14px 0">');
    H.push('<p style="color:#666;font-size:12px;font-style:italic;margin:0">Rules and the number-trace ' +
      'guard are deterministic SuiteScript. The embedded N/llm model only writes the reviewer and ' +
      'challenger notes; every figure in a note is verified in code. AI drafts, code checks, human ' +
      'approves. Advisory only — this never posts, approves, or reverses an entry.</p>');
    H.push('</div>');

    return {
      subject: meta.title + ' — ' + meta.period + ' — ' + escalate + ' to escalate',
      body: H.join('\n')
    };
  }

  function entryBlock(H, r, ccy) {
    var a = r.assessment, je = a.je;
    var d = DISPOSITION[r.final_disposition] || DISPOSITION.monitor;
    H.push('<div style="border:1px solid #e5e7eb;border-left:4px solid ' + d.color +
      ';border-radius:6px;padding:10px 14px;margin:10px 0;background:' + d.bg + '">');
    H.push('<div style="font-size:15px"><strong>' + esc(je.je_id) + '</strong> — ' +
      '<strong style="color:' + d.color + '">' + d.label + '</strong>' +
      ' <span style="color:#666">(score ' + a.risk_score + ', ' + esc(a.tier) + ')</span>' +
      (r.note_guard_passed ? '' : ' <span style="color:#b91c1c">⚠️ note failed the audit seam — do not rely on it</span>') +
      '</div>');
    H.push('<div style="font-size:13px;color:#333;margin:4px 0">' + esc(je.account) + ' (' + esc(je.account_type) +
      ') · ' + money(je.amount, ccy) + ' ' + esc(je.dr_cr || '') + ' · period ' + esc(je.period || je.period_id) +
      ' · prepared by ' + esc(je.preparer || 'n/a') +
      (je.approver ? ', approved by ' + esc(je.approver) : ', <strong>unapproved</strong>') + '</div>');
    if (je.description) H.push('<div style="font-size:12px;color:#666;font-style:italic;margin:0 0 6px">' + esc(je.description) + '</div>');

    H.push('<div style="font-size:12px;margin:4px 0"><strong>Flags:</strong><ul style="margin:2px 0 6px">');
    a.flags.forEach(function (f) {
      H.push('<li><code>' + esc(f.rule) + '</code> (' + esc(f.severity) + ') — ' + esc(f.detail) + '</li>');
    });
    H.push('</ul></div>');

    H.push('<div style="font-size:13px;margin:4px 0"><strong>Reviewer</strong> (' + esc(r.review.model) +
      ', ' + esc(r.review.residual_risk) + '). ' + esc(r.review.note) +
      (r.review.recommended_action ? '<br><span style="color:#666;font-size:12px">Recommended: ' +
        esc(r.review.recommended_action) + '</span>' : '') + '</div>');
    H.push('<div style="font-size:13px;margin:4px 0"><strong>Challenger</strong> (' + esc(r.challenge.model) +
      ', <strong>' + esc(r.challenge.verdict) + '</strong>). ' + esc(r.challenge.rationale) + '</div>');
    H.push('</div>');
  }

  function count(arr, pred) { return arr.reduce(function (s, x) { return s + (pred(x) ? 1 : 0); }, 0); }

  return { buildEmail: buildEmail };
});
