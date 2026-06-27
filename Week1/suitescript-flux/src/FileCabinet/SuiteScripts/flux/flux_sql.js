/**
 * flux_sql.js  -  SuiteQL builders for the flux review (deterministic; no AI, no N modules).
 *
 * These mirror the Python build's ns_flux_sql.py 1:1 so the calculation is identical across the two
 * implementations. The orchestrator runs them with N/query.runSuiteQL. Account ids / period ids are
 * coerced to integers before being inlined, so the IN-lists carry no injection risk.
 *
 * @NApiVersion 2.1
 */
define([], function () {

  function ints(arr) {
    return (arr || []).map(function (v) { return parseInt(v, 10); })
      .filter(function (v) { return !isNaN(v); }).join(', ');
  }

  // Income-statement account types -> 'Income Statement', else 'Balance Sheet'. Lets us emit a
  // Classification column without the saved search, and pick the common-size base later.
  var PL_TYPES = ['Income', 'COGS', 'Expense', 'OthIncome', 'OthExpense'];

  /**
   * The 14 most recent monthly periods ending on/before last month-end, newest first. The caller
   * takes [0]=current, [1]=prior, [0..HISTORY_MONTHS-1]=trailing, [HISTORY_MONTHS]=same-period-last-year.
   */
  function recentPeriodsSql() {
    return [
      "SELECT id, periodname, enddate",
      "FROM accountingperiod",
      "WHERE isadjustment = 'F' AND isquarter = 'F' AND isyear = 'F'",
      "  AND TRUNC(enddate) <= LAST_DAY(ADD_MONTHS(TRUNC(SYSDATE), -1))",
      "ORDER BY enddate DESC",
      "FETCH FIRST 14 ROWS ONLY"
    ].join('\n');
  }

  /**
   * Per (subsidiary, account) periodic current vs prior + the classification/type. Periodic = the
   * period's activity (one posting period each side), matching the saved search's Month-N Periodic.
   */
  function fluxSql(currId, priorId, book) {
    var types = PL_TYPES.map(function (t) { return "'" + t + "'"; }).join(', ');
    return [
      "SELECT t.subsidiary AS subsidiary_id, BUILTIN.DF(t.subsidiary) AS subsidiary,",
      "       a.id AS account_id, a.fullname AS account, a.accttype AS accttype,",
      "       CASE WHEN a.accttype IN (" + types + ") THEN 'Income Statement' ELSE 'Balance Sheet' END AS classification,",
      "       NVL(SUM(CASE WHEN t.postingperiod = " + parseInt(currId, 10) + "  THEN tal.amount END), 0) AS current_amt,",
      "       NVL(SUM(CASE WHEN t.postingperiod = " + parseInt(priorId, 10) + " THEN tal.amount END), 0) AS prior_amt",
      "FROM transactionaccountingline tal",
      "JOIN transaction t ON t.id = tal.transaction",
      "JOIN account a ON a.id = tal.account",
      "WHERE t.posting = 'T'",
      "  AND tal.accountingbook = " + parseInt(book, 10),
      "  AND t.postingperiod IN (" + parseInt(currId, 10) + ", " + parseInt(priorId, 10) + ")",
      "GROUP BY t.subsidiary, BUILTIN.DF(t.subsidiary), a.id, a.fullname, a.accttype"
    ].join('\n');
  }

  /**
   * Grounded drivers behind the flagged accounts, both periods, with memo/department/class so the
   * narrative can cite the source. Mirrors drivers_by_id_sql(with_grounding=True). Cap to the top N
   * per (account, period) in code (flux_calc.topDrivers) - SuiteQL window-over-SELECT* is unreliable.
   */
  function driversSql(accountIds, periodIds, book, subsidiaryIds) {
    var sub = (subsidiaryIds && subsidiaryIds.length)
      ? "\n  AND t.subsidiary IN (" + ints(subsidiaryIds) + ")" : '';
    return [
      "SELECT a.id AS account_id, a.fullname AS account, t.postingperiod AS period_id,",
      "       t.subsidiary AS subsidiary_id, BUILTIN.DF(t.subsidiary) AS subsidiary,",
      "       t.type AS txn_type, t.tranid AS tranid, BUILTIN.DF(t.entity) AS entity,",
      "       COUNT(*) AS lines, ROUND(SUM(tal.amount), 2) AS amount,",
      "       t.memo AS txn_memo, tl.memo AS line_memo,",
      "       BUILTIN.DF(tl.department) AS department, BUILTIN.DF(tl.class) AS class",
      "FROM transactionaccountingline tal",
      "JOIN transaction t ON t.id = tal.transaction",
      "JOIN account a ON a.id = tal.account",
      "JOIN transactionline tl ON tl.transaction = tal.transaction AND tl.id = tal.transactionline",
      "WHERE t.posting = 'T'",
      "  AND tal.accountingbook = " + parseInt(book, 10),
      "  AND tal.account IN (" + ints(accountIds) + ")",
      "  AND t.postingperiod IN (" + ints(periodIds) + ")" + sub,
      "GROUP BY a.id, a.fullname, t.postingperiod, t.subsidiary, BUILTIN.DF(t.subsidiary),",
      "         t.type, t.tranid, BUILTIN.DF(t.entity), t.memo, tl.memo,",
      "         BUILTIN.DF(tl.department), BUILTIN.DF(tl.class)",
      "ORDER BY a.id, t.postingperiod, ABS(SUM(tal.amount)) DESC"
    ].join('\n');
  }

  /** Trailing history: one pre-aggregated row per (account, period[, entity]). Feeds trend_facts. */
  function historySql(accountIds, periodIds, book, subsidiaryIds) {
    var sub = (subsidiaryIds && subsidiaryIds.length)
      ? "\n  AND t.subsidiary IN (" + ints(subsidiaryIds) + ")" : '';
    return [
      "SELECT a.id AS account_id, t.postingperiod AS period_id, t.subsidiary AS subsidiary_id,",
      "       BUILTIN.DF(t.entity) AS entity, COUNT(*) AS lines, ROUND(SUM(tal.amount), 2) AS amount",
      "FROM transactionaccountingline tal",
      "JOIN transaction t ON t.id = tal.transaction",
      "JOIN account a ON a.id = tal.account",
      "WHERE t.posting = 'T'",
      "  AND tal.accountingbook = " + parseInt(book, 10),
      "  AND tal.account IN (" + ints(accountIds) + ")",
      "  AND t.postingperiod IN (" + ints(periodIds) + ")" + sub,
      "GROUP BY a.id, t.postingperiod, t.subsidiary, BUILTIN.DF(t.entity)"
    ].join('\n');
  }

  return {
    PL_TYPES: PL_TYPES,
    recentPeriodsSql: recentPeriodsSql,
    fluxSql: fluxSql,
    driversSql: driversSql,
    historySql: historySql
  };
});
