/**
 * flux_report.js  -  deterministic HTML report assembler (mirrors ns_flux_report.py). Numbers come
 * from the data; the only AI text is each verified narrative. A narrative that failed the eval is
 * withheld and replaced by a flag - never shipped.
 *
 * @NApiVersion 2.1
 */
define([], function () {

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function money(v, ccy) { return ccy + ' ' + (Math.round(Number(v) || 0)).toLocaleString('en-US'); }
  function pct(p) { return p == null ? 'n/a' : (p >= 0 ? '+' : '') + (p * 100).toFixed(1) + '%'; }
  function dim(v) {
    var s = String(v == null ? '' : v).trim();
    return /^(|-none-|none|0)$/i.test(s.replace(/\s/g, '')) ? '' : s;
  }

  function buildEmail(meta, reviewRows) {
    var ccy = meta.currency;
    var flagged = reviewRows.length;
    var verified = reviewRows.filter(function (r) { return r.eval_ok; }).length;
    var showDept = reviewRows.some(function (r) { return dim(r.department); });
    var showClass = reviewRows.some(function (r) { return dim(r['class']); });

    var cell = 'padding:6px 8px;border:1px solid #ddd';
    var rcell = 'text-align:right;' + cell;
    var H = [];
    H.push('<div style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;max-width:820px">');
    H.push('<h2 style="margin:0 0 2px">' + esc(meta.title) + ' - ' + esc(meta.subsidiary) + '</h2>');
    H.push('<div style="color:#666;font-size:13px;margin-bottom:12px"><strong>' +
      esc(meta.current_period) + ' vs ' + esc(meta.prior_period) + '</strong> &nbsp;|&nbsp; generated ' +
      esc(meta.run_at) + '</div>');
    H.push('<p style="font-size:14px;margin:0 0 6px">Tolerance gate: absolute swing &ge; ' +
      money(meta.abs_threshold, ccy) + ' <strong>and</strong> (new account <strong>or</strong> swing &ge; ' +
      (meta.pct_threshold * 100).toFixed(0) + '%).</p>');
    H.push('<p style="font-size:14px;margin:0 0 14px"><strong>' + flagged +
      ' account(s) outside tolerance</strong>, ' + meta.ok_count +
      ' within tolerance. Narratives passing the number/provenance check: <strong>' + verified + '/' + flagged +
      '</strong>. <em>Calculated by NetSuite + SuiteScript; narrated by N/llm; every figure verified in code.</em></p>');

    var th = function (label, right) { return '<th style="' + (right ? rcell : 'text-align:left;' + cell) + '">' + label + '</th>'; };
    H.push('<table style="border-collapse:collapse;font-size:13px;width:100%"><thead><tr style="background:#f3f4f6">');
    H.push(th('Subsidiary') + th('Account') + (showDept ? th('Department') : '') + (showClass ? th('Class') : '') +
      th('Prior', 1) + th('Current', 1) + th('SPLY', 1) + th('YTD', 1) + th('Variance', 1) + th('%', 1) + th('Direction'));
    H.push('</tr></thead><tbody>');
    reviewRows.forEach(function (r, i) {
      var bg = i % 2 ? ' style="background:#fafafa"' : '';
      var td = function (v, right) { return '<td style="' + (right ? rcell : cell) + '">' + v + '</td>'; };
      H.push('<tr' + bg + '>' +
        td(esc(r.subsidiary)) + td(esc(r.account)) +
        (showDept ? td(esc(dim(r.department))) : '') + (showClass ? td(esc(dim(r['class']))) : '') +
        td(money(r.prior_amt, ccy), 1) + td(money(r.current_amt, ccy), 1) +
        td(r.sply_amount == null ? 'n/a' : money(r.sply_amount, ccy), 1) +
        td(r.ytd_amount == null ? 'n/a' : money(r.ytd_amount, ccy), 1) +
        td(money(r.variance_abs, ccy), 1) + td(pct(r.variance_pct), 1) + td(esc(r.direction)) + '</tr>');
    });
    H.push('</tbody></table>');

    H.push('<h3 style="margin:18px 0 4px">Explanations</h3>');
    reviewRows.forEach(function (r) {
      var label = esc(r.subsidiary ? r.subsidiary + ' - ' + r.account : r.account);
      if (r.eval_ok) {
        var extra = [];
        if (r.confidence) extra.push('Confidence: ' + r.confidence.level + (r.confidence.reason ? ' - ' + r.confidence.reason : ''));
        if (r.sensitivity) extra.push('Sensitivity (±' + (r.sensitivity.pct * 100).toFixed(0) + '%): variance ' +
          money(r.sensitivity.variance_down, ccy) + ' to ' + money(r.sensitivity.variance_up, ccy) +
          '; flag holds at downside: ' + (r.sensitivity.flag_holds_down ? 'yes' : 'no'));
        var tail = extra.length ? '<br><span style="color:#666;font-size:12px">' + esc(extra.join(' | ')) + '</span>' : '';
        H.push('<p style="font-size:13px;margin:0 0 10px"><strong>' + label + '.</strong> ' + esc(r.narrative) + tail + '</p>');
      } else {
        H.push('<p style="font-size:13px;background:#fef2f2;border:1px solid #fecaca;padding:8px 10px;border-radius:4px;margin:6px 0 10px">' +
          '<strong>' + label + ' - withheld, failed verification.</strong> The drafted explanation contained a figure or vendor not traceable ' +
          'to source and was not shipped. Variance: ' + money(r.variance_abs, ccy) + ' (' + pct(r.variance_pct) + '). Manual review required.</p>');
      }
      (r.assumptions || []).forEach(function (a) {
        H.push('<p style="font-size:12px;background:#fff7ed;border:1px solid #fed7aa;padding:7px 10px;border-radius:4px;margin:4px 0 10px">' +
          '<strong>Assumption (unverified).</strong> ' + esc(a) + '</p>');
      });
    });
    (meta.notes || []).forEach(function (n) {
      H.push('<p style="font-size:13px;background:#fff7ed;border:1px solid #fed7aa;padding:8px 10px;border-radius:4px;margin:6px 0 10px">' +
        '<strong>Reviewer note.</strong> ' + esc(n) + '</p>');
    });
    H.push('<hr style="border:none;border-top:1px solid #ddd;margin:14px 0">');
    H.push('<p style="color:#666;font-size:12px;font-style:italic;margin:0">Calculation and checks are deterministic ' +
      '(NetSuite SuiteQL + number/provenance eval, all in SuiteScript). The embedded N/llm model only turns the flagged ' +
      'transactions into plain-language explanations. AI drafts, code checks, human approves. DRAFT for review - not yet sent to finance.</p>');
    H.push('</div>');

    return {
      subject: meta.title + ' - ' + meta.subsidiary + ' - ' + meta.current_period + ' (DRAFT for review)',
      body: H.join('\n')
    };
  }

  return { buildEmail: buildEmail };
});
