/**
 * je_sql.js  -  SuiteQL builders for the manual-JE register (deterministic; no AI, no N modules).
 *
 * The register is assembled from three queries the orchestrator runs with N/query.runSuiteQL:
 *   1. recentPeriodsSql()      - the periods in scope + which ones are CLOSED (native flag).
 *   2. journalHeaderSql()      - one row per manual journal (id, dates, preparer, approver, memo, total).
 *   3. journalLinesSql()       - the lines behind those journals (account + type + amount), grouped in
 *                                code to pick the representative account and the sensitive-account flag.
 *
 * SEARCH-channel notes carried over from the flux build (these bit us there, avoided here):
 *   - SuiteQL rejects `FETCH FIRST n ROWS ONLY` -> use an Oracle ROWNUM subquery, re-sort outside it.
 *   - Header fields that error NOT_EXPOSED on the SEARCH channel are read from `transactionline`.
 * Ids are coerced to integers before being inlined, so the IN-lists carry no injection risk.
 *
 * @NApiVersion 2.1
 */
define([], function () {

  function ints(arr) {
    return (arr || []).map(function (v) { return parseInt(v, 10); })
      .filter(function (v) { return !isNaN(v); }).join(', ');
  }

  /**
   * The recent monthly periods ending on/before last month-end, newest first, each tagged with the
   * native `closed` flag so rule_closed_period needs no hard-coded list. [0] = most recent open month.
   */
  function recentPeriodsSql() {
    return [
      "SELECT id, periodname, enddate, closed, alllocked FROM (",
      "  SELECT id, periodname, enddate, closed, alllocked",
      "  FROM accountingperiod",
      "  WHERE isadjust = 'F' AND isquarter = 'F' AND isyear = 'F'",
      "    AND TRUNC(enddate) <= LAST_DAY(TRUNC(SYSDATE))",
      "  ORDER BY enddate DESC",
      ") WHERE ROWNUM <= 15",
      "ORDER BY enddate DESC"
    ].join('\n');
  }

  /**
   * One row per MANUAL journal in the given periods: document number, effective (tran) date, the
   * created timestamp we use as the posting time, the posting period, preparer (createdby), the
   * configured approver column, the memo, and the journal's total debit value.
   *
   * `approverCol` is injected from config (default 'nextapprover'); it is validated against a small
   * allow-list by the caller so it cannot inject SQL.
   */
  function journalHeaderSql(periodIds, book, approverCol, supportCol) {
    approverCol = approverCol || 'nextapprover';
    // Optional checkbox body field recording whether support is attached (see je_config.HAS_SUPPORT_FIELD).
    var supSel = supportCol ? "       t." + supportCol + " AS has_support_raw,\n" : '';
    var supGrp = supportCol ? "         t." + supportCol + ",\n" : '';
    return [
      "SELECT t.id AS je_id, t.tranid AS tranid, t.trandate AS trandate,",
      "       t.createddate AS created_ts, t.postingperiod AS period_id,",
      "       BUILTIN.DF(t.createdby) AS preparer,",
      "       BUILTIN.DF(t." + approverCol + ") AS approver,",
      supSel +
      "       t.memo AS memo, t.approvalstatus AS approvalstatus,",
      "       NVL(SUM(CASE WHEN tal.amount > 0 THEN tal.amount ELSE 0 END), 0) AS amount",
      "FROM transaction t",
      "JOIN transactionaccountingline tal ON tal.transaction = t.id",
      "WHERE t.type = 'Journal'",
      "  AND t.posting = 'T'",
      "  AND tal.accountingbook = " + parseInt(book, 10),
      "  AND t.postingperiod IN (" + ints(periodIds) + ")",
      "GROUP BY t.id, t.tranid, t.trandate, t.createddate, t.postingperiod,",
      "         BUILTIN.DF(t.createdby), BUILTIN.DF(t." + approverCol + "),",
      supGrp +
      "         t.memo, t.approvalstatus",
      "ORDER BY t.trandate DESC, t.id DESC"
    ].join('\n');
  }

  /**
   * The lines behind the flagged journals: account, its type, and the signed amount. The orchestrator
   * groups by je_id to pick the representative account (a sensitive account wins, else the largest
   * line) and to compute the debit/credit direction. account.sspecacct/accttype give the type.
   */
  function journalLinesSql(journalIds, book) {
    return [
      "SELECT tal.transaction AS je_id, a.id AS account_id, a.fullname AS account,",
      "       a.accttype AS accttype, ROUND(tal.amount, 2) AS amount",
      "FROM transactionaccountingline tal",
      "JOIN account a ON a.id = tal.account",
      "WHERE tal.accountingbook = " + parseInt(book, 10),
      "  AND tal.transaction IN (" + ints(journalIds) + ")",
      "ORDER BY tal.transaction, ABS(tal.amount) DESC"
    ].join('\n');
  }

  /** Count of manual journals per period, so the orchestrator can skip empty (e.g. current) months. */
  function journalCountsSql(periodIds, book) {
    return [
      "SELECT t.postingperiod AS period_id, COUNT(DISTINCT t.id) AS cnt",
      "FROM transaction t",
      "JOIN transactionaccountingline tal ON tal.transaction = t.id",
      "WHERE t.type = 'Journal' AND t.posting = 'T'",
      "  AND tal.accountingbook = " + parseInt(book, 10),
      "  AND t.postingperiod IN (" + ints(periodIds) + ")",
      "GROUP BY t.postingperiod"
    ].join('\n');
  }

  return {
    recentPeriodsSql: recentPeriodsSql,
    journalCountsSql: journalCountsSql,
    journalHeaderSql: journalHeaderSql,
    journalLinesSql: journalLinesSql
  };
});
