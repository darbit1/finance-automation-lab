/**
 * flux_calc.js  -  deterministic calc: tolerance gate, variance facts, vendor bridge, trend, top-N.
 * Ported 1:1 from the Python build's ns_flux_sql.py. No AI, no N modules -> unit-testable in isolation.
 *
 * @NApiVersion 2.1
 */
define([], function () {

  function toFloat(v) {
    if (v === null || v === undefined) return 0;
    var s = String(v).trim().replace(/,/g, '');
    if (s === '' || s === '-') return 0;
    var n = parseFloat(s);
    return isNaN(n) ? 0 : n;
  }

  function toInt(v) {
    if (v === null || v === undefined) return null;
    var n = parseInt(String(v).trim().replace(/,/g, ''), 10);
    return isNaN(n) ? null : n;
  }

  function round(n, dp) { var f = Math.pow(10, dp); return Math.round(n * f) / f; }

  /** Variance facts for one account. pct is null when prior == 0 (no divide-by-zero). */
  function varianceMetrics(prior, current) {
    var variance = round(current - prior, 2);
    var pct = (prior === 0) ? null : round(variance / Math.abs(prior), 4);
    var direction;
    if (prior === 0 && current !== 0) direction = 'new';
    else if (current === 0 && prior !== 0) direction = 'cleared';
    else if (variance > 0) direction = 'increase';
    else if (variance < 0) direction = 'decrease';
    else direction = 'flat';
    return { variance_abs: variance, variance_pct: pct, direction: direction };
  }

  /** The tolerance gate as one predicate. */
  function isReview(prior, current, abs, pct) {
    var variance = current - prior;
    if (Math.abs(variance) < abs) return false;
    return prior === 0 || Math.abs(variance / Math.abs(prior)) >= pct;
  }

  /**
   * Apply the gate to flux query rows (keys current_amt/prior_amt as numbers or strings). Returns the
   * flagged rows, each enriched with prior_amt/current_amt + variance facts, plus the ok_count.
   */
  function flagReviews(rows, abs, pct) {
    var reviews = [], okCount = 0;
    (rows || []).forEach(function (row) {
      var prior = toFloat(row.prior_amt);
      var current = toFloat(row.current_amt);
      if (isReview(prior, current, abs, pct)) {
        var m = varianceMetrics(prior, current);
        var rec = {};
        for (var k in row) if (row.hasOwnProperty(k)) rec[k] = row[k];
        rec.prior_amt = prior; rec.current_amt = current;
        rec.variance_abs = m.variance_abs; rec.variance_pct = m.variance_pct; rec.direction = m.direction;
        reviews.push(rec);
      } else {
        okCount += 1;
      }
    });
    return { reviews: reviews, ok_count: okCount };
  }

  /** Keep only the N largest drivers (by |amount|) per (account, period). */
  function topDrivers(driverRows, n) {
    var groups = {};
    (driverRows || []).forEach(function (r) {
      var key = String(r.account_id) + '|' + String(r.period_id);
      (groups[key] = groups[key] || []).push(r);
    });
    var out = [];
    Object.keys(groups).forEach(function (key) {
      var rows = groups[key].slice().sort(function (a, b) {
        return Math.abs(toFloat(b.amount)) - Math.abs(toFloat(a.amount));
      });
      out = out.concat(rows.slice(0, n));
    });
    return out;
  }

  /**
   * Decompose one account's movement BY VENDOR. drivers = rows for [current, prior]; filter to one
   * account (and subsidiary). Rows with no entity are bucketed under their tranid. status:
   * new | dropped | increased | decreased | unchanged. Sorted by |delta|.
   */
  function vendorBridge(drivers, accountId, currentPeriodId, priorPeriodId, subsidiaryId) {
    var cur = {}, pri = {};
    (drivers || []).forEach(function (d) {
      if (toInt(d.account_id) !== accountId) return;
      if (subsidiaryId != null && toInt(d.subsidiary_id) !== subsidiaryId) return;
      var key = (d.entity ? String(d.entity).trim() : '') || ('(journal ' + (d.tranid || 'n/a') + ')');
      var pid = toInt(d.period_id), amt = toFloat(d.amount);
      if (pid === currentPeriodId) cur[key] = (cur[key] || 0) + amt;
      else if (pid === priorPeriodId) pri[key] = (pri[key] || 0) + amt;
    });
    var keys = {};
    Object.keys(cur).forEach(function (k) { keys[k] = 1; });
    Object.keys(pri).forEach(function (k) { keys[k] = 1; });
    var bridge = Object.keys(keys).map(function (entity) {
      var c = round(cur[entity] || 0, 2), p = round(pri[entity] || 0, 2), delta = round(c - p, 2);
      var status;
      if (p === 0 && c !== 0) status = 'new';
      else if (c === 0 && p !== 0) status = 'dropped';
      else if (Math.abs(delta) <= 0.005) status = 'unchanged';
      else status = delta > 0 ? 'increased' : 'decreased';
      return { entity: entity, prior: p, current: c, delta: delta, status: status };
    });
    bridge.sort(function (a, b) { return Math.abs(b.delta) - Math.abs(a.delta); });
    return bridge;
  }

  /**
   * Trend signals for one account from history rows. orderedPeriodIds: oldest->newest trailing window.
   * Returns periods_present, consecutive_months, is_recurring, trailing_avg, sply_amount, vs_sply_pct.
   */
  function trendFacts(historyRows, accountId, orderedPeriodIds, subsidiaryId, splyPeriodId, recurringMin) {
    recurringMin = recurringMin || 3;
    var amt = {};
    (historyRows || []).forEach(function (r) {
      if (toInt(r.account_id) !== accountId) return;
      if (subsidiaryId != null && toInt(r.subsidiary_id) !== subsidiaryId) return;
      var pid = toInt(r.period_id);
      if (pid === null) return;
      amt[pid] = (amt[pid] || 0) + toFloat(r.amount);
    });
    var series = (orderedPeriodIds || []).map(function (pid) { return round(amt[pid] || 0, 2); });
    var nonzero = series.filter(function (v) { return Math.abs(v) > 0; });
    var consecutive = 0;
    for (var i = series.length - 1; i >= 0; i--) { if (Math.abs(series[i]) > 0) consecutive++; else break; }
    var trailingAvg = nonzero.length
      ? round(nonzero.reduce(function (a, b) { return a + b; }, 0) / nonzero.length, 2) : 0;
    var splyAmount = (splyPeriodId != null && amt.hasOwnProperty(splyPeriodId))
      ? round(amt[splyPeriodId], 2) : null;
    var current = series.length ? series[series.length - 1] : 0;
    var vsSplyPct = splyAmount ? round((current - splyAmount) / Math.abs(splyAmount), 4) : null;
    return {
      periods_present: nonzero.length, consecutive_months: consecutive,
      is_recurring: nonzero.length >= recurringMin, trailing_avg: trailingAvg,
      sply_amount: splyAmount, vs_sply_pct: vsSplyPct
    };
  }

  /** +/-pct sensitivity on the current figure + whether the REVIEW flag survives the downside. */
  function sensitivity(row, pct, abs, pctThreshold) {
    pct = pct || 0.05;
    var prior = toFloat(row.prior_amt), current = toFloat(row.current_amt);
    var up = current * (1 + pct), down = current * (1 - pct);
    return {
      pct: pct, variance_up: round(up - prior, 2), variance_down: round(down - prior, 2),
      flag_holds_down: isReview(prior, down, abs, pctThreshold)
    };
  }

  /** Confidence from data completeness (coverage of the swing + memo/comparison context). */
  function confidenceScore(row, drivers, trend) {
    var base = Math.abs(toFloat(row.variance_abs)) || Math.abs(toFloat(row.current_amt));
    var explained = (drivers || []).reduce(function (s, d) { return s + Math.abs(toFloat(d.amount)); }, 0);
    var coverage = base === 0 ? null : Math.min(explained / base, 1);
    var hasContext = (drivers || []).some(function (d) { return d.txn_memo || d.line_memo; });
    var comparable = !!(trend && (trend.sply_amount != null || trend.is_recurring));
    var cov = coverage || 0, level, reason;
    if (cov >= 0.80 && (hasContext || comparable)) {
      level = 'high'; reason = 'drivers explain the swing and memo/comparison context is available';
    } else if (cov < 0.50 && !(hasContext || comparable)) {
      level = 'low'; reason = 'drivers explain little of the swing and no memo/comparison context';
    } else {
      level = 'medium'; reason = 'partial coverage or limited context';
    }
    return { level: level, reason: reason, coverage: coverage === null ? null : round(coverage, 4) };
  }

  return {
    toFloat: toFloat, toInt: toInt, round: round,
    varianceMetrics: varianceMetrics, isReview: isReview, flagReviews: flagReviews,
    topDrivers: topDrivers, vendorBridge: vendorBridge, trendFacts: trendFacts,
    sensitivity: sensitivity, confidenceScore: confidenceScore
  };
});
