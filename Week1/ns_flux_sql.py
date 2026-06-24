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
                      accounting_book: int = 1, subsidiary_ids: Sequence[int] = None) -> str:
    """
    Drivers for the saved-search flow, where the search returns account INTERNAL IDs and groups
    per (subsidiary, account). Single book. Includes tranid so a reviewer / the AI can spot test or
    one-off postings, and emits subsidiary_id so the caller can match each driver row back to a
    flagged (subsidiary, account) row.

    Pass subsidiary_ids (the flagged rows' Subsidiary Internal IDs) to scope the pull to those
    entities. The account_ids x subsidiary_ids IN-lists may over-pull cross pairs; the caller drops
    the extras by matching on (subsidiary_id, account_id).
    """
    sub_filter = f"\n  AND t.subsidiary IN ({_csv(subsidiary_ids)})" if subsidiary_ids else ""
    return f"""
SELECT a.id, a.fullname AS account, t.postingperiod AS period_id,
       t.subsidiary AS subsidiary_id, BUILTIN.DF(t.subsidiary) AS subsidiary,
       t.type AS txn_type, t.tranid, BUILTIN.DF(t.entity) AS entity,
       COUNT(*) AS lines, ROUND(SUM(tal.amount),2) AS amount
FROM transactionaccountingline tal
JOIN transaction t ON t.id = tal.transaction
JOIN account a ON a.id = tal.account
WHERE t.posting = 'T'
  AND tal.accountingbook = {accounting_book}
  AND tal.account IN ({_csv(account_ids)})
  AND t.postingperiod IN ({_csv(period_ids)}){sub_filter}
GROUP BY a.id, a.fullname, t.postingperiod, t.subsidiary, BUILTIN.DF(t.subsidiary), t.type, t.tranid, BUILTIN.DF(t.entity)
ORDER BY a.id, t.postingperiod, ABS(SUM(tal.amount)) DESC
""".strip()


# --- Tolerance gate (row processing, not SQL) --------------------------------
# The saved-search flow applies the gate in code (the search returns the difference but no flag).
# Keeping it here - tested and version-controlled - means every deterministic step is committed
# code, not authored ad-hoc each run.

def _to_float(v) -> float:
    """Parse a saved-search numeric cell ('1,234.5', '-50', '', None) to float."""
    if v is None:
        return 0.0
    s = str(v).strip().replace(",", "")
    return float(s) if s not in ("", "-") else 0.0


def variance_metrics(prior: float, current: float) -> dict:
    """Deterministic variance facts for one account. variance_pct is None when prior == 0
    (no divide-by-zero). direction: new | cleared | increase | decrease | flat."""
    variance = round(current - prior, 2)
    pct = None if prior == 0 else round(variance / abs(prior), 4)
    if prior == 0 and current != 0:
        direction = "new"
    elif current == 0 and prior != 0:
        direction = "cleared"
    elif variance > 0:
        direction = "increase"
    elif variance < 0:
        direction = "decrease"
    else:
        direction = "flat"
    return {"variance_abs": variance, "variance_pct": pct, "direction": direction}


def is_review(prior: float, current: float,
              abs_threshold: float = 25000.0, pct_threshold: float = 0.10) -> bool:
    """The tolerance gate, as one predicate: flag when the absolute swing is material AND the
    account is new-from-zero OR the percentage swing is material."""
    variance = current - prior
    if abs(variance) < abs_threshold:
        return False
    return prior == 0 or abs(variance / abs(prior)) >= pct_threshold


def flag_reviews(rows, abs_threshold: float = 25000.0, pct_threshold: float = 0.10,
                 current_key: str = "Month - 1", prior_key: str = "Month - 2"):
    """Apply the tolerance gate to parsed saved-search rows (dicts; numeric cells may be strings).
    Returns (review_rows, ok_count). Each review_row is the original dict plus prior_amt,
    current_amt, variance_abs, variance_pct, direction. The model never runs this - it is the
    deterministic 'what gets flagged' step."""
    reviews, ok_count = [], 0
    for row in rows:
        prior = _to_float(row.get(prior_key))
        current = _to_float(row.get(current_key))
        if is_review(prior, current, abs_threshold, pct_threshold):
            reviews.append({**row, "prior_amt": prior, "current_amt": current,
                            **variance_metrics(prior, current)})
        else:
            ok_count += 1
    return reviews, ok_count


if __name__ == "__main__":
    # Smoke: print the queries with placeholder args (no real data).
    print(flux_sql("<SUBSIDIARY>", 0, 0, 25000, 0.10))
    print("\n---\n")
    print(drivers_sql("<SUBSIDIARY>", [0, 0], ["<ACCT1>", "<ACCT2>"]))
