/**
 * je_scheduled.js  -  the manual-JE anomaly review, end to end, inside NetSuite.
 *
 * Orchestrates: pull the manual-journal register (SuiteQL) -> deterministic rules + risk score
 * (je_rules) -> per flagged entry, the embedded N/llm reviewer + a challenger (je_review_ai) with the
 * number-trace guard (je_guard) between them -> a reviewer worklist emailed as a DRAFT + saved to the
 * File Cabinet. RIGHT-SIZE THE AI: every flag, score and disposition is deterministic; the model only
 * writes the two notes; code has the last word (a "missed risk" challenge forces escalation).
 *
 * @NApiVersion 2.1
 * @NScriptType ScheduledScript
 */
define(['N/query', 'N/email', 'N/file', 'N/runtime', 'N/log',
  './je_config', './je_sql', './je_rules', './je_review_ai', './je_guard', './je_report'],
function (query, email, file, runtime, log, CONFIG, sql, rules, ai, guard, report) {

  // Only these columns may be injected as the approver/support field ids (defence-in-depth: the
  // config is admin-set, but we still allow-list what can reach the SQL string).
  var SAFE_COL = /^[a-z0-9_]+$/i;

  function param(name, fallback) {
    try {
      var v = runtime.getCurrentScript().getParameter({ name: name });
      return (v === null || v === undefined || v === '') ? fallback : v;
    } catch (e) { return fallback; }
  }

  function cfg() {
    return {
      book: parseInt(param('custscript_je_book', CONFIG.ACCOUNTING_BOOK), 10),
      months: parseInt(param('custscript_je_months', CONFIG.REVIEW_MONTHS), 10),
      approvalThreshold: parseFloat(param('custscript_je_threshold', CONFIG.APPROVAL_THRESHOLD)),
      roundMin: CONFIG.ROUND_MIN, gapDays: CONFIG.GAP_DAYS,
      businessStart: CONFIG.BUSINESS_START, businessEnd: CONFIG.BUSINESS_END,
      dupWindowDays: CONFIG.DUP_WINDOW_DAYS, shortDescLen: CONFIG.SHORT_DESC_LEN,
      sensitiveTypes: CONFIG.SENSITIVE_TYPES,
      enableApproverRules: boolParam('custscript_je_approver_rules', CONFIG.ENABLE_APPROVER_RULES),
      approverField: safeCol(param('custscript_je_approver_field', CONFIG.APPROVER_FIELD), 'nextapprover'),
      supportField: safeCol(param('custscript_je_support_field', CONFIG.HAS_SUPPORT_FIELD), ''),
      supportDefault: CONFIG.HAS_SUPPORT_DEFAULT,
      reviewer: param('custscript_je_reviewer', CONFIG.REVIEWER_EMAIL),
      authorEmail: param('custscript_je_author', CONFIG.AUTHOR_EMAIL),
      authorId: param('custscript_je_authorid', CONFIG.AUTHOR_EMPLOYEE_ID),
      folderId: parseInt(param('custscript_je_folder', CONFIG.REPORT_FOLDER_ID), 10),
      reviewerModel: param('custscript_je_model', CONFIG.REVIEWER_MODEL),
      challengerModel: param('custscript_je_model_chal', CONFIG.CHALLENGER_MODEL),
      currency: CONFIG.CURRENCY, title: CONFIG.REPORT_TITLE
    };
  }

  function safeCol(v, fallback) { return (v && SAFE_COL.test(v)) ? v : fallback; }
  function boolParam(name, fallback) {
    var v = param(name, null);
    if (v === null) return fallback;
    return !(v === false || v === 'F' || v === 'f' || v === 'false' || v === '0' || v === 0);
  }
  function runQuery(sqlText) { return query.runSuiteQL({ query: sqlText }).asMappedResults(); }

  function execute() {
    var c = cfg();
    var runAt = new Date().toISOString().replace('T', ' ').substring(0, 16) + ' UTC';

    // 1. Periods: newest first, with the native closed flag. Take the most recent `months` in scope.
    var periods = runQuery(sql.recentPeriodsSql());
    if (!periods.length) { log.error('JE review', 'Could not resolve accounting periods'); return; }
    var scope = periods.slice(0, Math.max(1, c.months));
    var scopeIds = scope.map(function (p) { return rules_toInt(p.id); });
    var periodName = {}, closedPeriodIds = {};
    periods.forEach(function (p) {
      periodName[String(p.id)] = p.periodname;
      if (isTrue(p.closed) || isTrue(p.alllocked)) closedPeriodIds[String(p.id)] = true;
    });
    var scopeLabel = scope.map(function (p) { return p.periodname; }).join(', ');

    // 2. Manual-journal headers in scope.
    var headers = runQuery(sql.journalHeaderSql(scopeIds, c.book, c.approverField, c.supportField));
    var meta = { title: c.title, period: scopeLabel, currency: c.currency, run_at: runAt };
    if (!headers.length) {
      var emptyOut = report.buildEmail(meta, []);
      sendAndSave(c, meta, emptyOut);
      log.audit('JE review', 'No manual journals in ' + scopeLabel);
      return;
    }

    // 3. Lines behind those journals -> group to a representative account + dr/cr per journal.
    var jeIds = headers.map(function (h) { return rules_toInt(h.je_id); });
    var lines = runQuery(sql.journalLinesSql(jeIds, c.book));
    var linesByJe = {};
    lines.forEach(function (l) {
      var k = String(l.je_id);
      (linesByJe[k] = linesByJe[k] || []).push(l);
    });

    // 4. Assemble the register of entry objects the rules operate on.
    var register = headers.map(function (h) {
      var rep = representativeAccount(linesByJe[String(h.je_id)] || [], c.sensitiveTypes);
      var hasSupport = (c.supportField && h.hasOwnProperty('has_support_raw'))
        ? isTrue(h.has_support_raw) : c.supportDefault;
      return {
        je_id: h.tranid || ('JE' + h.je_id),
        entry_date: new Date(h.trandate),
        post_ts: new Date(h.created_ts || h.trandate),
        period_id: rules_toInt(h.period_id),
        period: periodName[String(h.period_id)] || String(h.period_id),
        account: rep.account, account_type: rep.account_type,
        amount: Number(h.amount) || 0, dr_cr: rep.dr_cr,
        preparer: h.preparer || '', approver: h.approver || '',
        description: h.memo || '', has_support: hasSupport
      };
    });

    // 5. Deterministic assessment (rules + score + tier).
    var ctx = rules.contextFromConfig(c, closedPeriodIds, []);   // no native holiday source; weekend/after-hours still fire
    var assessments = rules.assessRegister(register, ctx);

    // 6. Maker-checker. Only the grey-zone (high/medium) entries reach the model — low/clear are
    //    accepted deterministically (right-size the token spend + respect the N/llm call quota).
    var results = assessments.map(function (a) { return makerChecker(a, c); });

    // 7. Assemble + draft.
    var out = report.buildEmail(meta, results);
    sendAndSave(c, meta, out);

    var esc = results.filter(function (r) { return r.final_disposition === 'escalate'; }).length;
    var overrides = results.filter(function (r) { return r.challenge.verdict !== 'agree'; }).length;
    var withheld = results.filter(function (r) { return !r.note_guard_passed; }).length;
    log.audit('JE review summary', scopeLabel + ' | journals=' + results.length +
      ' | escalate=' + esc + ' | four-eyes overrides=' + overrides + ' | notes withheld=' + withheld);
  }

  /** Reviewer -> guard -> challenger for one entry, with code holding the last word on disposition. */
  function makerChecker(a, c) {
    var hasHigh = a.flags.some(function (f) { return f.severity === 'high'; });
    var note, ch, guardPass = true;

    if (a.tier === 'clear' || a.tier === 'low') {
      note = { je_id: a.je.je_id, residual_risk: 'accept',
        note: 'Risk score ' + a.risk_score + ', no material control concern. Logged, no reviewer action required.',
        recommended_action: 'None.', model: 'code' };
      ch = { je_id: a.je.je_id, verdict: 'agree', rationale: 'Below review threshold.', model: 'code' };
    } else {
      try {
        note = ai.review(a, c.reviewerModel);
      } catch (e) {
        // Model/quota failure: fall back to a deterministic note so the control still runs.
        note = { je_id: a.je.je_id, residual_risk: ai.riskFromTier(a.tier),
          note: 'AI note unavailable (' + (e.message || e) + '). Score ' + a.risk_score + ' (' + a.tier + ').',
          recommended_action: '', model: c.reviewerModel + ' (unavailable)' };
        log.error('JE reviewer failed', a.je.je_id + ' :: ' + (e.message || e));
      }
      // Code guard-rail around the AI's judgement: any high-severity flag forces escalate.
      if ((a.tier === 'high' || hasHigh) && note.residual_risk !== 'escalate') note.residual_risk = 'escalate';

      var g = guard.guardNote(note, a);
      guardPass = g.ok;
      if (!guardPass) log.audit('JE note withheld', a.je.je_id + ' :: untraceable=' + JSON.stringify(g.offenders));

      try {
        ch = ai.challenge(a, note, c.challengerModel);
      } catch (e2) {
        ch = ai.deterministicChallenge(a, note, c.challengerModel + ' (unavailable)');
        log.error('JE challenger failed', a.je.je_id + ' :: ' + (e2.message || e2));
      }
    }

    return { assessment: a, review: note, challenge: ch, note_guard_passed: guardPass,
             final_disposition: finalDisposition(note, ch) };
  }

  // Code has the last word: a missed_risk challenge forces escalation; a false_positive can only
  // soften an over-escalation to monitor; otherwise the reviewer's call stands.
  function finalDisposition(note, ch) {
    if (ch.verdict === 'missed_risk') return 'escalate';
    if (ch.verdict === 'false_positive') return note.residual_risk === 'escalate' ? 'monitor' : note.residual_risk;
    return note.residual_risk;
  }

  /** Pick the account that best represents a journal: a sensitive account wins, else the largest line. */
  function representativeAccount(jeLines, sensitiveTypes) {
    if (!jeLines.length) return { account: '(no line)', account_type: 'other', dr_cr: '' };
    var best = null, bestSensitive = null;
    jeLines.forEach(function (l) {
      var cat = rules.normalizeAcctType(l.accttype);
      var absAmt = Math.abs(Number(l.amount) || 0);
      if (!best || absAmt > Math.abs(Number(best.amount) || 0)) best = l;
      if (sensitiveTypes[cat] && (!bestSensitive || absAmt > Math.abs(Number(bestSensitive.amount) || 0))) bestSensitive = l;
    });
    var chosen = bestSensitive || best;
    return {
      account: chosen.account, account_type: rules.normalizeAcctType(chosen.accttype),
      dr_cr: (Number(chosen.amount) || 0) >= 0 ? 'DR' : 'CR'
    };
  }

  function isTrue(v) { return v === true || v === 'T' || v === 't' || v === 1 || v === '1'; }
  function rules_toInt(v) { var n = parseInt(String(v).replace(/,/g, ''), 10); return isNaN(n) ? null : n; }

  // --- email author + folder resolution (same realities as the flux build) ---------------------
  function resolveAuthorId(emailAddr, explicitId) {
    if (explicitId && parseInt(explicitId, 10) > 0) return parseInt(explicitId, 10);
    try {
      var esc = String(emailAddr).replace(/'/g, "''");
      var rows = runQuery("SELECT id FROM employee WHERE UPPER(email) = UPPER('" + esc + "')");
      if (rows.length) return rules_toInt(rows[0].id);
      var cand = runQuery("SELECT id, email FROM employee WHERE email LIKE '%@darbit.nl'");
      log.audit('JE author candidates', 'no match for ' + emailAddr + '; candidates=' + JSON.stringify(cand.slice(0, 15)));
    } catch (e) { log.error('JE author lookup failed', e.message || e); }
    return runtime.getCurrentUser().id;
  }

  function resolveFolderId(name) {
    try {
      var rows = runQuery("SELECT id FROM mediaitemfolder WHERE name = '" + String(name).replace(/'/g, "''") + "'");
      if (rows.length) return rules_toInt(rows[0].id);
    } catch (e) { log.error('JE folder lookup failed', e.message || e); }
    return null;
  }

  function sendAndSave(c, meta, out) {
    var authorId = resolveAuthorId(c.authorEmail, c.authorId);
    try {
      email.send({ author: authorId, recipients: c.reviewer, subject: out.subject, body: out.body });
      log.audit('JE email sent', 'author employee ' + authorId + ' -> ' + c.reviewer);
    } catch (e) {
      log.error('JE email failed', 'author=' + authorId + ' -> ' + c.reviewer + ' :: ' + (e.message || e));
    }
    var folderId = (c.folderId && c.folderId > 0) ? c.folderId : resolveFolderId('je_review');
    if (folderId) {
      try {
        var fileId = file.create({
          name: 'je_review_' + String(meta.period).replace(/[^\w]+/g, '_') + '.html',
          fileType: file.Type.HTMLDOC, contents: out.body, folder: folderId
        }).save();
        log.audit('JE report saved', 'File Cabinet file id ' + fileId + ' in folder ' + folderId);
      } catch (e2) { log.error('JE file save failed', e2.message || e2); }
    } else {
      log.error('JE file not saved', 'Could not resolve a folder; set REPORT_FOLDER_ID in je_config.js');
    }
  }

  return { execute: execute };
});
