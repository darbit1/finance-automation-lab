/**
 * flux_scheduled.js  -  the monthly flux review, end to end, inside NetSuite.
 *
 * Orchestrates the deterministic helpers + the embedded N/llm narrative + the audit-seam eval, then
 * emails the reviewer a DRAFT report and saves it to the File Cabinet. RIGHT-SIZE THE AI: every figure
 * is computed by SuiteQL/SuiteScript; the model only writes prose; flux_eval verifies it before it
 * ships. No figure the model invents can survive the check.
 *
 * @NApiVersion 2.1
 * @NScriptType ScheduledScript
 */
define(['N/query', 'N/email', 'N/file', 'N/runtime', 'N/log',
  './flux_config', './flux_sql', './flux_calc', './flux_eval', './flux_narrative', './flux_report'],
function (query, email, file, runtime, log, CONFIG, sql, calc, evalSeam, narr, report) {

  function param(name, fallback) {
    try {
      var v = runtime.getCurrentScript().getParameter({ name: name });
      return (v === null || v === undefined || v === '') ? fallback : v;
    } catch (e) { return fallback; }
  }

  function cfg() {
    return {
      abs: parseFloat(param('custscript_flux_abs', CONFIG.ABS_THRESHOLD)),
      pct: parseFloat(param('custscript_flux_pct', CONFIG.PCT_THRESHOLD)),
      book: parseInt(param('custscript_flux_book', CONFIG.ACCOUNTING_BOOK), 10),
      historyMonths: parseInt(param('custscript_flux_history', CONFIG.HISTORY_MONTHS), 10),
      topN: CONFIG.TOP_DRIVERS,
      reviewer: param('custscript_flux_reviewer', CONFIG.REVIEWER_EMAIL),
      folderId: parseInt(param('custscript_flux_folder', CONFIG.REPORT_FOLDER_ID), 10),
      model: param('custscript_flux_model', CONFIG.MODEL_FAMILY),
      currency: CONFIG.CURRENCY,
      title: CONFIG.REPORT_TITLE
    };
  }

  function runQuery(sqlText) {
    return query.runSuiteQL({ query: sqlText }).asMappedResults();
  }

  function key(subId, acctId) { return String(subId) + '|' + String(acctId); }

  function execute() {
    var c = cfg();
    var runAt = new Date().toISOString().replace('T', ' ').substring(0, 16) + ' UTC';

    // 1. Periods (newest first): [0]=current, [1]=prior, [0..H-1]=trailing, [H]=same-period-last-year.
    var periods = runQuery(sql.recentPeriodsSql());
    if (periods.length < 2) { log.error('Flux', 'Could not resolve current/prior periods'); return; }
    var currId = calc.toInt(periods[0].id), priorId = calc.toInt(periods[1].id);
    var currName = periods[0].periodname, priorName = periods[1].periodname;
    var trailing = periods.slice(0, c.historyMonths).map(function (p) { return calc.toInt(p.id); });
    var orderedTrailing = trailing.slice().reverse();                       // oldest -> newest
    var splyId = periods.length > c.historyMonths ? calc.toInt(periods[c.historyMonths].id) : null;

    // 2-3. Flux calc (SuiteQL) + tolerance gate (code).
    var fluxRows = runQuery(sql.fluxSql(currId, priorId, c.book));
    var flagged = calc.flagReviews(fluxRows, c.abs, c.pct);
    var reviews = flagged.reviews;

    var meta = {
      title: c.title, subsidiary: 'Consolidated', current_period: currName, prior_period: priorName,
      abs_threshold: c.abs, pct_threshold: c.pct, currency: c.currency, run_at: runAt,
      ok_count: flagged.ok_count, notes: []
    };

    if (!reviews.length) {
      var emptyEmail = report.buildEmail(meta, []);
      sendAndSave(c, meta, emptyEmail);
      log.audit('Flux', 'No accounts outside tolerance for ' + currName);
      return;
    }

    // 4. Grounded drivers + trailing history (SuiteQL), once for all flagged accounts.
    var acctIds = reviews.map(function (r) { return calc.toInt(r.account_id); });
    var subIds = {};
    reviews.forEach(function (r) { subIds[calc.toInt(r.subsidiary_id)] = 1; });
    subIds = Object.keys(subIds).map(function (s) { return parseInt(s, 10); });

    var drivers = calc.topDrivers(runQuery(sql.driversSql(acctIds, [currId, priorId], c.book, subIds)), c.topN);
    var historyPeriods = splyId != null ? trailing.concat([splyId]) : trailing;
    var history = runQuery(sql.historySql(acctIds, historyPeriods, c.book, subIds));

    var driversByKey = {};
    drivers.forEach(function (d) {
      var k = key(calc.toInt(d.subsidiary_id), calc.toInt(d.account_id));
      (driversByKey[k] = driversByKey[k] || []).push(d);
    });

    // 5-7. Per account: facts -> AI narrative -> verify.
    reviews.forEach(function (r) {
      var subId = calc.toInt(r.subsidiary_id), acctId = calc.toInt(r.account_id);
      var rowDrivers = driversByKey[key(subId, acctId)] || [];
      var bridge = calc.vendorBridge(rowDrivers, acctId, currId, priorId, subId);
      var trend = calc.trendFacts(history, acctId, orderedTrailing, subId, splyId);
      r.subsidiary = r.subsidiary || '';
      r.sply_amount = trend.sply_amount;
      r.ytd_amount = null;                                  // YTD lives in the saved-search Python build
      r.confidence = calc.confidenceScore(r, rowDrivers, trend);
      r.sensitivity = calc.sensitivity(r, 0.05, c.abs, c.pct);

      var ctx = narr.buildContext(r, rowDrivers, bridge, trend, meta);
      var extra = {};
      ['sply_amount', 'trailing_avg', 'vs_sply_pct', 'consecutive_months', 'periods_present']
        .forEach(function (k2) { if (trend[k2] != null) extra['trend_' + k2] = trend[k2]; });
      bridge.forEach(function (b, i) { extra['bridge_' + i] = b.delta; });

      try {
        var text = narr.generate(ctx.prompt, c.model);
        var verdict = evalSeam.checkExplanation(text,
          { prior: r.prior_amt, current: r.current_amt, variance_abs: r.variance_abs, variance_pct: r.variance_pct },
          rowDrivers, { extra_facts: extra, allowed_refs: ctx.refs });
        r.narrative = text;
        r.eval_ok = verdict.ok;
        if (!verdict.ok) log.audit('Flux withheld', r.account + ' :: bad=' + JSON.stringify(verdict.bad_numbers) + '/' + JSON.stringify(verdict.bad_entities));
      } catch (e) {
        r.narrative = '';
        r.eval_ok = false;
        log.error('Flux narrative failed', r.account + ' :: ' + (e.message || e));
      }
    });

    // 8. Assemble + draft (email reviewer, save file).
    var out = report.buildEmail(meta, reviews);
    sendAndSave(c, meta, out);

    var verified = reviews.filter(function (r) { return r.eval_ok; }).length;
    log.audit('Flux summary', currName + ' vs ' + priorName + ' | REVIEW=' + reviews.length +
      ' | verified=' + verified + ' | within tolerance=' + flagged.ok_count);
  }

  function sendAndSave(c, meta, out) {
    try {
      email.send({
        author: runtime.getCurrentUser().id,
        recipients: c.reviewer,
        subject: out.subject,
        body: out.body
      });
    } catch (e) {
      log.error('Flux email failed', e.message || e);
    }
    if (c.folderId && c.folderId > 0) {
      try {
        file.create({
          name: 'flux_' + meta.current_period.replace(/\s+/g, '_') + '.html',
          fileType: file.Type.HTMLDOC,
          contents: out.body,
          folder: c.folderId
        }).save();
      } catch (e2) {
        log.error('Flux file save failed', e2.message || e2);
      }
    }
  }

  return { execute: execute };
});
