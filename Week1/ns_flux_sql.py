"""
ns_flux_sql.py  -  genericised SuiteQL builders for the flux automation (deterministic).

These produce the exact queries the pipeline runs against NetSuite. No real account, entity,
or period is baked in - the caller passes them at run time. The flux query mirrors the saved
search's formula logic 1:1, so it doubles as the validation/cross-check of the saved search.

Right-size note: the calculation (variance, %, tolerance) and the driver grouping are both
deterministic SuiteQL. The AI never sees a query - only the structured rows they return.
"""

from typing import Sequence

# Income-statement account types (P&L flux). Drop this filter for a full trial-balance flux.
PL_TYPES = ("Income", "COGS", "Expense", "OthIncome", "OthExpense")


def _q(s: str) -> str:
    """Single-quote escape for SuiteQL string literals."""
    return s.replace("'", "''")


def _csv(items: Sequence) -> str:
    return ", ".join(str(i) for i in items)


def _types_csv(types: Sequence[str]) -> str:
    return ", ".join(f"'{_q(t)}'" for t in types)


def period_lookup_sql(*period_names: str) -> str:
    """Resolve posting-period names to internal IDs (saved search uses names, SuiteQL uses IDs)."""
    names = ", ".join(f"'{_q(n)}'" for n in period_names)
    return f"SELECT id, periodname FROM accountingperiod WHERE periodname IN ({names})"


def flux_sql(subsidiary: str, curr_id: int, prior_id: int,
             abs_threshold: float, pct_threshold: float,
             accttypes: Sequence[str] = PL_TYPES, accounting_book: int = 1,
             review_only: bool = False) -> str:
    """
    Per-account current/prior/variance/% + direction + within_tolerance flag.
    Identical logic to the saved-search formulas; use it to validate the saved search and as
    the pipeline's calc source until the saved search exists.

    accounting_book defaults to 1 (primary). transactionaccountingline holds one row per book,
    so WITHOUT this filter a multi-book account is summed across books and the variance is
    over-stated. Always pin the book the saved search reports on.

    review_only=True filters server-side to the flagged rows only. Prefer this for any run that
    feeds the AI/report: a trial balance is mostly flat, so returning only REVIEW rows turns a
    few-hundred-row result into a handful and is the single biggest token saver.
    """
    review_filter = "WHERE f.within_tolerance = 'REVIEW'" if review_only else ""
    return f"""
SELECT f.account, f.accttype, f.current_amt, f.prior_amt, f.variance_abs,
       f.variance_pct, f.direction, f.within_tolerance
FROM (
  SELECT
    x.account, x.accttype,
    ROUND(x.current_amt,2) AS current_amt,
    ROUND(x.prior_amt,2)   AS prior_amt,
    ROUND(x.current_amt - x.prior_amt,2) AS variance_abs,
    CASE WHEN x.prior_amt = 0 THEN NULL
         ELSE ROUND((x.current_amt - x.prior_amt)/ABS(x.prior_amt),4) END AS variance_pct,
    CASE WHEN x.prior_amt = 0 AND x.current_amt <> 0 THEN 'new'
         WHEN x.current_amt = 0 AND x.prior_amt <> 0 THEN 'cleared'
         WHEN x.current_amt - x.prior_amt > 0 THEN 'increase'
         WHEN x.current_amt - x.prior_amt < 0 THEN 'decrease'
         ELSE 'flat' END AS direction,
    CASE WHEN ABS(x.current_amt - x.prior_amt) >= {abs_threshold}
              AND (x.prior_amt = 0 OR ABS((x.current_amt - x.prior_amt)/ABS(x.prior_amt)) >= {pct_threshold})
         THEN 'REVIEW' ELSE 'OK' END AS within_tolerance
  FROM (
    SELECT a.acctnumber, a.fullname AS account, a.accttype,
      NVL(SUM(CASE WHEN t.postingperiod = {curr_id}  THEN tal.amount END),0) AS current_amt,
      NVL(SUM(CASE WHEN t.postingperiod = {prior_id} THEN tal.amount END),0) AS prior_amt
    FROM transactionaccountingline tal
    JOIN transaction t ON t.id = tal.transaction
    JOIN account a ON a.id = tal.account
    JOIN subsidiary s ON s.id = t.subsidiary
    WHERE t.posting = 'T'
      AND tal.accountingbook = {accounting_book}
      AND s.name = '{_q(subsidiary)}'
      AND t.postingperiod IN ({curr_id}, {prior_id})
      AND a.accttype IN ({_types_csv(accttypes)})
    GROUP BY a.acctnumber, a.fullname, a.accttype
  ) x
) f
{review_filter}
ORDER BY ABS(f.variance_abs) DESC
""".strip()


def drivers_sql(subsidiary: str, period_ids: Sequence[int], acctnumbers: Sequence[str],
                accounting_book: int = 1) -> str:
    """
    Pre-aggregated drivers behind the flagged accounts, for BOTH periods, grouped by
    period / transaction type / vendor, ranked by size. This compact table is the ONLY
    transaction context the AI sees (right-sized: not raw lines). Single book by default.
    """
    accts = ", ".join(f"'{_q(a)}'" for a in acctnumbers)
    return f"""
SELECT a.acctnumber, a.fullname AS account, t.postingperiod AS period_id,
       t.type AS txn_type, t.tranid, BUILTIN.DF(t.entity) AS entity,
       COUNT(*) AS lines, ROUND(SUM(tal.amount),2) AS amount
FROM transactionaccountingline tal
JOIN transaction t ON t.id = tal.transaction
JOIN account a ON a.id = tal.account
JOIN subsidiary s ON s.id = t.subsidiary
WHERE t.posting = 'T'
  AND tal.accountingbook = {accounting_book}
  AND s.name = '{_q(subsidiary)}'
  AND t.postingperiod IN ({_csv(period_ids)})
  AND a.acctnumber IN ({accts})
GROUP BY a.acctnumber, a.fullname, t.postingperiod, t.type, t.tranid, BUILTIN.DF(t.entity)
ORDER BY a.acctnumber, t.postingperiod, ABS(SUM(tal.amount)) DESC
""".strip()


def drivers_by_id_sql(account_ids: Sequence[int], period_ids: Sequence[int],
                      accounting_book: int = 1) -> str:
    """
    Drivers for the saved-search flow, where the search returns account INTERNAL IDs and is
    CONSOLIDATED (no subsidiary filter). Same pre-aggregation as drivers_sql, single book.
    Includes tranid so a reviewer / the AI can spot test or one-off postings.
    """
    return f"""
SELECT a.id, a.fullname AS account, t.postingperiod AS period_id,
       BUILTIN.DF(t.subsidiary) AS subsidiary, t.type AS txn_type, t.tranid,
       BUILTIN.DF(t.entity) AS entity, COUNT(*) AS lines, ROUND(SUM(tal.amount),2) AS amount
FROM transactionaccountingline tal
JOIN transaction t ON t.id = tal.transaction
JOIN account a ON a.id = tal.account
WHERE t.posting = 'T'
  AND tal.accountingbook = {accounting_book}
  AND tal.account IN ({_csv(account_ids)})
  AND t.postingperiod IN ({_csv(period_ids)})
GROUP BY a.id, a.fullname, t.postingperiod, BUILTIN.DF(t.subsidiary), t.type, t.tranid, BUILTIN.DF(t.entity)
ORDER BY a.id, t.postingperiod, ABS(SUM(tal.amount)) DESC
""".strip()


if __name__ == "__main__":
    # Smoke: print the queries with placeholder args (no real data).
    print(flux_sql("<SUBSIDIARY>", 0, 0, 25000, 0.10))
    print("\n---\n")
    print(drivers_sql("<SUBSIDIARY>", [0, 0], ["<ACCT1>", "<ACCT2>"]))
