/**
 * je_rules.js  -  THE DETERMINISTIC RULE ENGINE (ported 1:1 from Week3/je_rules.py).
 *
 * Ten pure functions raise the flags; a deterministic score maps them to a risk tier. No AI, no N
 * modules -> unit-testable off-platform (see __tests__/je_rules.test.js). The N/llm layer only comes
 * afterwards to judge the grey-zone cases and challenge itself; it never decides a flag or a figure.
 *
 * An entry (assembled by the orchestrator from je_sql results) has:
 *   je_id, entry_date(Date), post_ts(Date), period_id, account, account_type(normalised category),
 *   amount(Number), dr_cr, preparer, approver, description, has_support(bool).
 *
 * @NApiVersion 2.1
 */
define([], function () {

  var SEVERITY_WEIGHT = { high: 3, medium: 2, low: 1 };

  var GENERIC_DESC = {
    adjustment: 1, adj: 1, reclass: 1, correction: 1, 'to correct': 1, 'true up': 1,
    'true-up': 1, plug: 1, misc: 1, journal: 1, entry: 1
  };

  /**
   * Map a raw NetSuite accttype to the category the rules use. Control = AP/AR subledger accounts;
   * bank = bank/clearing; equity = equity/retained earnings. Everything else is expense/revenue/other.
   */
  function normalizeAcctType(accttype) {
    switch (String(accttype || '')) {
      case 'Bank': return 'bank';
      case 'AcctPay': case 'AcctRec': return 'control';
      case 'Equity': case 'RetEarnings': return 'equity';
      case 'Income': case 'OthIncome': return 'revenue';
      case 'Expense': case 'COGS': case 'OthExpense': return 'expense';
      default: return 'other';
    }
  }

  function flag(rule, severity, detail) { return { rule: rule, severity: severity, detail: detail }; }

  function money(v) { return (Math.round(Number(v) || 0)).toLocaleString('en-US'); }

  // days between two Dates (b - a), calendar days.
  function dayDiff(a, b) {
    var ms = 24 * 60 * 60 * 1000;
    return Math.round((toDate(b).getTime() - toDate(a).getTime()) / ms);
  }
  function toDate(d) { return (d instanceof Date) ? d : new Date(d); }

  // ==========================================================================
  // The rules — each pure: (entry, ctx) -> flag | null
  // ==========================================================================
  function ruleOverThreshold(je, ctx) {
    if (Number(je.amount) >= ctx.approvalThreshold) {
      return flag('over_threshold', 'medium',
        'amount ' + money(je.amount) + ' >= approval threshold ' + money(ctx.approvalThreshold));
    }
    return null;
  }

  function ruleRoundThousand(je, ctx) {
    var amt = Number(je.amount);
    if (amt >= ctx.roundMin && amt % 1000 === 0) {
      return flag('round_thousand', 'low', 'amount ' + money(amt) + ' is an exact multiple of 1,000');
    }
    return null;
  }

  function ruleOffHours(je, ctx) {
    var ts = toDate(je.post_ts);
    var reasons = [];
    var dow = ts.getDay();                       // 0=Sun .. 6=Sat
    if (dow === 0 || dow === 6) reasons.push('weekend');
    if (isHoliday(ts, ctx.holidays)) reasons.push('holiday');
    var h = ts.getHours();
    if (h < ctx.businessStart || h >= ctx.businessEnd) {
      reasons.push(pad(h) + ':' + pad(ts.getMinutes()) + ' outside ' +
        pad(ctx.businessStart) + ':00-' + pad(ctx.businessEnd) + ':00');
    }
    if (reasons.length) {
      return flag('off_hours', 'low', 'posted ' + reasons.join(', ') + ' (' + fmtTs(ts) + ')');
    }
    return null;
  }

  function ruleWeakDescription(je, ctx) {
    var desc = String(je.description || '').trim();
    if (!desc) return flag('weak_description', 'medium', 'description is blank');
    var low = desc.toLowerCase();
    if (desc.length < ctx.shortDescLen || GENERIC_DESC.hasOwnProperty(low)) {
      return flag('weak_description', 'low', 'description uninformative: "' + desc + '"');
    }
    return null;
  }

  function ruleNoSupport(je, ctx) {
    if (!je.has_support) {
      var sev = Number(je.amount) >= ctx.approvalThreshold ? 'high' : 'medium';
      return flag('no_support', sev, 'no supporting document (amount ' + money(je.amount) + ')');
    }
    return null;
  }

  function ruleSensitiveAccount(je, ctx) {
    if (ctx.sensitiveTypes[je.account_type]) {
      return flag('sensitive_account', 'high',
        'manual JE to ' + je.account_type + ' account "' + je.account + '"');
    }
    return null;
  }

  function ruleEntryPostGap(je, ctx) {
    var gap = dayDiff(je.entry_date, je.post_ts);
    if (gap >= ctx.gapDays) {
      return flag('entry_post_gap', 'medium',
        gap + ' days between entry date ' + fmtDate(je.entry_date) + ' and posting ' + fmtDate(je.post_ts));
    }
    return null;
  }

  function ruleClosedPeriod(je, ctx) {
    if (ctx.closedPeriodIds[String(je.period_id)]) {
      return flag('closed_period', 'high', 'posted into closed period ' + (je.period || je.period_id));
    }
    return null;
  }

  function ruleSodBreach(je, ctx) {
    var preparer = String(je.preparer || '').trim();
    var approver = String(je.approver || '').trim();
    if (approver && preparer && preparer === approver) {
      return flag('sod_breach', 'high', 'preparer and approver are the same person (' + preparer + ')');
    }
    if (!approver) {
      return flag('sod_breach', 'medium', 'no independent approver recorded (preparer ' + (preparer || 'n/a') + ')');
    }
    return null;
  }

  function ruleNearDuplicate(je, ctx) {
    var reg = ctx.register || [];
    for (var i = 0; i < reg.length; i++) {
      var other = reg[i];
      if (other === je || other.je_id === je.je_id) continue;
      if (other.account === je.account &&
          Math.abs(Number(other.amount) - Number(je.amount)) < 0.01 &&
          Math.abs(dayDiff(je.post_ts, other.post_ts)) <= ctx.dupWindowDays) {
        return flag('near_duplicate', 'medium',
          'matches ' + other.je_id + ': same account "' + je.account + '", amount ' +
          money(je.amount) + ', within ' + ctx.dupWindowDays + 'd');
      }
    }
    return null;
  }

  var RULES = [
    ruleOverThreshold, ruleRoundThousand, ruleOffHours, ruleWeakDescription, ruleNoSupport,
    ruleSensitiveAccount, ruleEntryPostGap, ruleClosedPeriod, ruleSodBreach, ruleNearDuplicate
  ];

  // ==========================================================================
  // Evaluation + deterministic scoring (mirrors the Python score()/assess())
  // ==========================================================================
  // Rules that depend on an approval workflow; skipped when ctx.enableApproverRules is false.
  var APPROVER_RULES = [ruleSodBreach];

  function evaluate(je, ctx) {
    var flags = [];
    for (var i = 0; i < RULES.length; i++) {
      if (ctx.enableApproverRules === false && APPROVER_RULES.indexOf(RULES[i]) !== -1) continue;
      var f = RULES[i](je, ctx);
      if (f) flags.push(f);
    }
    return flags;
  }

  function score(flags) {
    if (!flags.length) return { risk_score: 0, tier: 'clear' };
    var total = 0, hasHigh = false;
    flags.forEach(function (f) { total += SEVERITY_WEIGHT[f.severity]; if (f.severity === 'high') hasHigh = true; });
    var tier = (hasHigh || total >= 5) ? 'high' : (total >= 2 ? 'medium' : 'low');
    return { risk_score: total, tier: tier };
  }

  function assess(je, ctx) {
    var flags = evaluate(je, ctx);
    var s = score(flags);
    return { je: je, flags: flags, risk_score: s.risk_score, tier: s.tier,
             flag_rules: flags.map(function (f) { return f.rule; }) };
  }

  /** Assess a whole register. Points ctx.register at it so near-duplicate sees every other row. */
  function assessRegister(register, ctx) {
    ctx.register = register;
    return register.map(function (je) { return assess(je, ctx); });
  }

  // Build a RuleContext from a config object (defaults mirror je_rules.RuleContext in Python).
  function contextFromConfig(cfg, closedPeriodIds, holidays) {
    return {
      register: [],
      closedPeriodIds: closedPeriodIds || {},
      holidays: holidays || [],
      approvalThreshold: cfg.approvalThreshold != null ? cfg.approvalThreshold : 50000,
      roundMin: cfg.roundMin != null ? cfg.roundMin : 10000,
      gapDays: cfg.gapDays != null ? cfg.gapDays : 30,
      businessStart: cfg.businessStart != null ? cfg.businessStart : 7,
      businessEnd: cfg.businessEnd != null ? cfg.businessEnd : 19,
      dupWindowDays: cfg.dupWindowDays != null ? cfg.dupWindowDays : 7,
      shortDescLen: cfg.shortDescLen != null ? cfg.shortDescLen : 15,
      sensitiveTypes: cfg.sensitiveTypes || { control: 1, bank: 1, equity: 1 },
      enableApproverRules: cfg.enableApproverRules !== false
    };
  }

  // --- small helpers ---------------------------------------------------------
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function fmtDate(d) { d = toDate(d); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function fmtTs(d) { return fmtDate(d) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  function isHoliday(ts, holidays) {
    var key = fmtDate(ts);
    return (holidays || []).some(function (h) { return fmtDate(h) === key; });
  }

  return {
    SEVERITY_WEIGHT: SEVERITY_WEIGHT,
    normalizeAcctType: normalizeAcctType,
    ruleOverThreshold: ruleOverThreshold, ruleRoundThousand: ruleRoundThousand,
    ruleOffHours: ruleOffHours, ruleWeakDescription: ruleWeakDescription,
    ruleNoSupport: ruleNoSupport, ruleSensitiveAccount: ruleSensitiveAccount,
    ruleEntryPostGap: ruleEntryPostGap, ruleClosedPeriod: ruleClosedPeriod,
    ruleSodBreach: ruleSodBreach, ruleNearDuplicate: ruleNearDuplicate,
    RULES: RULES, evaluate: evaluate, score: score, assess: assess,
    assessRegister: assessRegister, contextFromConfig: contextFromConfig,
    fmtDate: fmtDate, fmtTs: fmtTs
  };
});
