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

# Account-type groupings for the common-size bases (NetSuite acct types).
REVENUE_TYPES = ("Income", "OthIncome")
ASSET_TYPES = ("Bank", "AcctRec", "OthCurrAsset", "FixedAsset", "OthAsset",
               "DeferExpense", "UnbilledRec", "InvtAsset")


def _q(s: str) -> str:
    """Single-quote escape for SuiteQL string literals."""
    return s.replace("'", "''")


def _csv(items: Sequence) -> str:
    return ", ".join(str(i) for i in items)


def _types_csv(types: Sequence[str]) -> str:
    return ", ".join(f"'{_q(t)}'" for t in types)


def period_lookup_sql(*period_names: str) -> str:
    """Resolve posting-period names to internal IDs (saved search uses names, SuiteQL uses IDs).

    Accepts the whole comparison set in one call - current, prior, same-period-last-year, and the
    YTD months - so a single lookup feeds the multi-period enrichments. The caller keeps the
    name->id map and passes the ids on to account_history_sql / trend_facts / period_total.
    """
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

    Periodic, not cumulative: current_amt/prior_amt each SUM tal.amount within ONE posting period,
    so each is that period's activity (the rebuilt saved search is also periodic-over-periodic).
    That makes this fallback a 1:1 cross-check of the saved search's Month-1/Month-2 columns.

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
                      accounting_book: int = 1, subsidiary_ids: Sequence[int] = None,
                      with_grounding: bool = False) -> str:
    """
    Drivers for the saved-search flow, where the search returns account INTERNAL IDs and groups
    per (subsidiary, account). Single book. Includes tranid so a reviewer / the AI can spot test or
    one-off postings, and emits subsidiary_id so the caller can match each driver row back to a
    flagged (subsidiary, account) row. Rows come pre-sorted by ABS(amount) within (account, period);
    cap them to the material few with top_drivers() in Python (SuiteQL window functions over a
    nested SELECT * proved unreliable on NetSuite, so the cap is done in code).

    Pass subsidiary_ids (the flagged rows' Subsidiary Internal IDs) to scope the pull to those
    entities. The account_ids x subsidiary_ids IN-lists may over-pull cross pairs; the caller drops
    the extras by matching on (subsidiary_id, account_id).

    with_grounding=True adds qualitative context for richer (still-auditable) narratives: the
    transaction memo + the line memo/department/class/location (via transactionline). These are the
    'why' the AI may cite; figures stay number-checked.
    """
    sub_filter = f"\n  AND t.subsidiary IN ({_csv(subsidiary_ids)})" if subsidiary_ids else ""
    if with_grounding:
        join_extra = "\nJOIN transactionline tl ON tl.transaction = tal.transaction AND tl.id = tal.transactionline"
        select_extra = (",\n       t.memo AS txn_memo, tl.memo AS line_memo,\n"
                        "       BUILTIN.DF(tl.department) AS department, "
                        "BUILTIN.DF(tl.class) AS class, BUILTIN.DF(tl.location) AS location")
        group_extra = (", t.memo, tl.memo, BUILTIN.DF(tl.department), "
                       "BUILTIN.DF(tl.class), BUILTIN.DF(tl.location)")
    else:
        join_extra = select_extra = group_extra = ""
    return f"""
SELECT a.id, a.fullname AS account, t.postingperiod AS period_id,
       t.subsidiary AS subsidiary_id, BUILTIN.DF(t.subsidiary) AS subsidiary,
       t.type AS txn_type, t.tranid, BUILTIN.DF(t.entity) AS entity,
       COUNT(*) AS lines, ROUND(SUM(tal.amount),2) AS amount{select_extra}
FROM transactionaccountingline tal
JOIN transaction t ON t.id = tal.transaction
JOIN account a ON a.id = tal.account{join_extra}
WHERE t.posting = 'T'
  AND tal.accountingbook = {accounting_book}
  AND tal.account IN ({_csv(account_ids)})
  AND t.postingperiod IN ({_csv(period_ids)}){sub_filter}
GROUP BY a.id, a.fullname, t.postingperiod, t.subsidiary, BUILTIN.DF(t.subsidiary), t.type, t.tranid, BUILTIN.DF(t.entity){group_extra}
ORDER BY a.id, t.postingperiod, ABS(SUM(tal.amount)) DESC""".strip()


def top_drivers(driver_rows, n: int = 8, account_key: str = "id", period_key: str = "period_id"):
    """Keep only the N largest drivers (by ABS(amount)) per (account, period) - so the grounded
    memos ride on the material rows, not every line. Done in code (portable; no SuiteQL window).
    Preserves input order within a group beyond the sort key being abs(amount) desc."""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in driver_rows:
        groups[(str(r.get(account_key)), str(r.get(period_key)))].append(r)
    out = []
    for rows in groups.values():
        rows = sorted(rows, key=lambda r: abs(_to_float(r.get("amount"))), reverse=True)
        out.extend(rows[:n])
    return out


def account_history_sql(account_ids: Sequence[int], period_ids: Sequence[int],
                        accounting_book: int = 1, subsidiary_ids: Sequence[int] = None,
                        by_entity: bool = False) -> str:
    """
    Trailing history for the flagged accounts: one PRE-AGGREGATED row per
    (account, period[, subsidiary[, entity]]) total, over the trailing periods passed (e.g. the
    last 12 months plus the same-period-last-year period). This is the 'compare more data' source -
    it lets trend_facts() decide recurrence / 'first time in N months' / SPLY comparison in code,
    so the AI never infers a trend itself. One row per period (not per transaction) => cheap.

    by_entity=True groups by vendor too, so trend_facts can see whether one vendor recurs across
    periods ('all invoices for the same vendor'). Single book; optional subsidiary scope.
    """
    sub_filter = f"\n  AND t.subsidiary IN ({_csv(subsidiary_ids)})" if subsidiary_ids else ""
    ent_select = ", BUILTIN.DF(t.entity) AS entity" if by_entity else ""
    ent_group = ", BUILTIN.DF(t.entity)" if by_entity else ""
    return f"""
SELECT a.id, a.fullname AS account, t.postingperiod AS period_id,
       t.subsidiary AS subsidiary_id{ent_select},
       COUNT(*) AS lines, ROUND(SUM(tal.amount),2) AS amount
FROM transactionaccountingline tal
JOIN transaction t ON t.id = tal.transaction
JOIN account a ON a.id = tal.account
WHERE t.posting = 'T'
  AND tal.accountingbook = {accounting_book}
  AND tal.account IN ({_csv(account_ids)})
  AND t.postingperiod IN ({_csv(period_ids)}){sub_filter}
GROUP BY a.id, a.fullname, t.postingperiod, t.subsidiary{ent_group}
ORDER BY a.id, t.postingperiod
""".strip()


# --- Tolerance gate + derived facts (row processing, not SQL) -----------------
# The saved-search flow applies the gate in code (the search returns the difference but no flag).
# Keeping these here - tested and version-controlled - means every deterministic step is committed
# code, not authored ad-hoc each run. The model never runs any of them.

def _to_float(v) -> float:
    """Parse a saved-search numeric cell ('1,234.5', '-50', '', None) to float."""
    if v is None:
        return 0.0
    s = str(v).strip().replace(",", "")
    return float(s) if s not in ("", "-") else 0.0


def _to_int(v):
    """Parse an internal-id cell to int (None when blank/non-numeric)."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return None


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
                 current_key: str = "Month - 1 Periodic", prior_key: str = "Month - 2 Periodic",
                 curr_ytd_key: str = "Month - 1 YTD", prior_ytd_key: str = "Month - 2 YTD"):
    """Apply the tolerance gate to parsed saved-search rows (dicts; numeric cells may be strings).
    Returns (review_rows, ok_count). Each review_row is the original dict plus prior_amt,
    current_amt, variance_abs, variance_pct, direction. The model never runs this - it is the
    deterministic 'what gets flagged' step.

    The gate runs on the PERIODIC columns (the month's activity), matching the saved search's
    Difference = Month-1 Periodic - Month-2 Periodic. When the YTD columns are present they are
    captured too (ytd_amount / prior_ytd_amount), so the report shows YTD straight from the search -
    no extra SuiteQL needed."""
    reviews, ok_count = [], 0
    for row in rows:
        prior = _to_float(row.get(prior_key))
        current = _to_float(row.get(current_key))
        if is_review(prior, current, abs_threshold, pct_threshold):
            rec = {**row, "prior_amt": prior, "current_amt": current,
                   **variance_metrics(prior, current)}
            if curr_ytd_key in row or prior_ytd_key in row:
                rec["ytd_amount"] = _to_float(row.get(curr_ytd_key))
                rec["prior_ytd_amount"] = _to_float(row.get(prior_ytd_key))
            reviews.append(rec)
        else:
            ok_count += 1
    return reviews, ok_count


def trend_facts(history_rows, account_id: int, ordered_period_ids: Sequence[int],
                subsidiary_id: int = None, sply_period_id: int = None,
                recurring_min: int = 3) -> dict:
    """
    Deterministic trend signals for one account from its trailing history (account_history_sql rows).
    ordered_period_ids is the trailing window OLDEST->NEWEST. The AI may only assert recurrence /
    'first time' / 'expected to normalise' / SPLY claims that match these facts - it never infers a
    trend on its own.

    Returns: periods_present (non-zero periods in the window), consecutive_months (run of non-zero
    periods ending at the newest), is_recurring (present in >= recurring_min periods), trailing_avg
    (mean of the non-zero period totals), sply_amount (same-period-last-year total, or None),
    vs_sply_pct (newest period vs SPLY, or None).
    """
    amt = {}
    for r in history_rows:
        if _to_int(r.get("id") if r.get("id") is not None else r.get("account_id")) != account_id:
            continue
        if subsidiary_id is not None and _to_int(r.get("subsidiary_id")) != subsidiary_id:
            continue
        pid = _to_int(r.get("period_id"))
        if pid is None:
            continue
        amt[pid] = amt.get(pid, 0.0) + _to_float(r.get("amount"))

    series = [round(amt.get(pid, 0.0), 2) for pid in ordered_period_ids]
    nonzero = [v for v in series if abs(v) > 0]
    periods_present = len(nonzero)

    consecutive = 0
    for v in reversed(series):
        if abs(v) > 0:
            consecutive += 1
        else:
            break

    trailing_avg = round(sum(nonzero) / len(nonzero), 2) if nonzero else 0.0
    sply_amount = round(amt[sply_period_id], 2) if (sply_period_id in amt) else None
    current = series[-1] if series else 0.0
    vs_sply_pct = round((current - sply_amount) / abs(sply_amount), 4) if sply_amount else None

    return {"periods_present": periods_present, "consecutive_months": consecutive,
            "is_recurring": periods_present >= recurring_min, "trailing_avg": trailing_avg,
            "sply_amount": sply_amount, "vs_sply_pct": vs_sply_pct}


def period_total(history_rows, account_id: int, period_ids: Sequence[int],
                 subsidiary_id: int = None) -> float:
    """Sum one account's history-row amounts across a set of periods - the deterministic YTD (pass the
    fiscal-year-to-date period ids) or prior-year-YTD total. Same row shape as account_history_sql."""
    wanted = {int(p) for p in period_ids}
    total = 0.0
    for r in history_rows:
        if _to_int(r.get("id") if r.get("id") is not None else r.get("account_id")) != account_id:
            continue
        if subsidiary_id is not None and _to_int(r.get("subsidiary_id")) != subsidiary_id:
            continue
        if _to_int(r.get("period_id")) in wanted:
            total += _to_float(r.get("amount"))
    return round(total, 2)


def vendor_bridge(drivers, account_id: int, current_period_id: int, prior_period_id: int,
                  subsidiary_id: int = None, unchanged_tol: float = 0.005):
    """
    Decompose one account's period-over-period movement BY VENDOR (deterministic). For each entity that
    posted to the account in either period, compare its prior-period total to its current-period total
    and classify the change. The AI never does this arithmetic - it just narrates the result.

    Answers the "same account, mix of vendors" case, e.g. Apr: vendor A EUR 100k -> May: vendor A
    EUR 50k + new vendor B EUR 75k, becomes:
      [{entity: 'Vendor B', prior: 0, current: 75000, delta: 75000, status: 'new'},
       {entity: 'Vendor A', prior: 100000, current: 50000, delta: -50000, status: 'decreased'}]
    (sorted by |delta|; net of the deltas = the account's variance).

    Rows with no entity (journals) are bucketed under their tranid (e.g. 'JE164589') so journal-only
    swings are still itemised. Pass drivers from drivers_by_id_sql for [current, prior]; filter to one
    account (and subsidiary, if the pull spanned several). status: new | dropped | increased |
    decreased | unchanged.
    """
    cur, pri = {}, {}
    for d in drivers:
        if _to_int(d.get("id") if d.get("id") is not None else d.get("account_id")) != account_id:
            continue
        if subsidiary_id is not None and _to_int(d.get("subsidiary_id")) != subsidiary_id:
            continue
        key = (d.get("entity") or "").strip() or f"(journal {d.get('tranid') or 'n/a'})"
        pid = _to_int(d.get("period_id"))
        amt = _to_float(d.get("amount"))
        if pid == current_period_id:
            cur[key] = cur.get(key, 0.0) + amt
        elif pid == prior_period_id:
            pri[key] = pri.get(key, 0.0) + amt

    bridge = []
    for entity in set(cur) | set(pri):
        c, p = round(cur.get(entity, 0.0), 2), round(pri.get(entity, 0.0), 2)
        delta = round(c - p, 2)
        if p == 0 and c != 0:
            status = "new"
        elif c == 0 and p != 0:
            status = "dropped"
        elif abs(delta) <= unchanged_tol:
            status = "unchanged"
        elif delta > 0:
            status = "increased"
        else:
            status = "decreased"
        bridge.append({"entity": entity, "prior": p, "current": c, "delta": delta, "status": status})
    bridge.sort(key=lambda b: abs(b["delta"]), reverse=True)
    return bridge


def common_size(rows, base: float, amount_key: str = "current_amt", out_key: str = "common_size_pct"):
    """Express each row's amount as a fraction of a base (revenue for a P&L line, total assets for a
    BS line). Deterministic - the common-size % is computed here, never by the AI. base == 0 -> None.
    Returns new dicts with out_key added."""
    b = _to_float(base)
    out = []
    for r in rows:
        v = _to_float(r.get(amount_key))
        out.append({**r, out_key: (None if b == 0 else round(v / abs(b), 4))})
    return out


def common_size_by_classification(review_rows, all_rows,
                                  classification_key: str = "Classification",
                                  accttype_key: str = "Account Type"):
    """Add common_size_pct per flagged row using its Classification (BS/IS) to pick the base,
    summed from the FULL saved-search result (all_rows):
      IS line -> share of total revenue (periodic, current month: 'Month - 1 Periodic')
      BS line -> share of total assets  (balance, current month: 'Month - 1 YTD')
    Convention-based - flip the measures/types here if your house style differs. Deterministic;
    the AI never computes a common-size %."""
    rev_base = sum(_to_float(r.get("Month - 1 Periodic")) for r in all_rows
                   if r.get(accttype_key) in REVENUE_TYPES)
    asset_base = sum(_to_float(r.get("Month - 1 YTD")) for r in all_rows
                     if r.get(accttype_key) in ASSET_TYPES)
    out = []
    for r in review_rows:
        cls = (r.get(classification_key) or "").strip().upper()
        # The saved search returns 'Income Statement' / 'Balance Sheet'; also accept the 'IS'/'BS'
        # short codes and 'P&L'.
        is_pl = cls.startswith("IS") or "INCOME" in cls or "P&L" in cls or "PROFIT" in cls
        is_bs = cls.startswith("BS") or "BALANCE" in cls
        if is_pl:
            base, amt = rev_base, _to_float(r.get("Month - 1 Periodic"))
        elif is_bs:
            base, amt = asset_base, _to_float(r.get("Month - 1 YTD"))
        else:
            base, amt = 0.0, 0.0
        out.append({**r, "common_size_pct": (None if base == 0 else round(amt / abs(base), 4))})
    return out


def confidence_score(review_row, drivers, trend: dict = None,
                     strong: float = 0.80, weak: float = 0.50) -> dict:
    """
    Deterministic data-completeness rating for one flagged account - NOT an LLM guess.

    coverage = |sum of the provided current-period driver amounts| / |variance| : how much of the
    swing is explained by named drivers. has_context = any driver carries a memo. comparable = a
    trend with SPLY or recurrence is available. Levels: high (well-covered AND we have context or a
    comparison), low (poorly covered and nothing else), medium otherwise.
    """
    base = abs(_to_float(review_row.get("variance_abs"))) or abs(_to_float(review_row.get("current_amt")))
    explained = sum(abs(_to_float(d.get("amount"))) for d in drivers)
    coverage = None if base == 0 else round(min(explained / base, 1.0), 4)
    has_context = any((d.get("txn_memo") or d.get("line_memo")) for d in drivers)
    comparable = bool(trend and (trend.get("sply_amount") is not None or trend.get("is_recurring")))

    cov = coverage or 0.0
    if cov >= strong and (has_context or comparable):
        level, reason = "high", "drivers explain the swing and memo/comparison context is available"
    elif cov < weak and not (has_context or comparable):
        level, reason = "low", "drivers explain little of the swing and no memo/comparison context"
    else:
        level, reason = "medium", "partial coverage or limited context"
    return {"level": level, "reason": reason, "coverage": coverage,
            "has_context": has_context, "comparable": comparable}


def sensitivity(review_row, pct: float = 0.05,
                abs_threshold: float = 25000.0, pct_threshold: float = 0.10) -> dict:
    """
    Deterministic +/-pct sensitivity on the current-period figure: how the variance moves and whether
    the REVIEW flag survives a downside shift. A flag that holds at -pct is a robust finding; one that
    flips is borderline. Computed, not asserted by the AI.
    """
    prior = _to_float(review_row.get("prior_amt"))
    current = _to_float(review_row.get("current_amt"))
    up, down = current * (1 + pct), current * (1 - pct)
    return {"pct": pct,
            "variance_up": round(up - prior, 2),
            "variance_down": round(down - prior, 2),
            "flag_holds_down": is_review(prior, down, abs_threshold, pct_threshold)}


if __name__ == "__main__":
    # Smoke: print the queries with placeholder args (no real data).
    print(flux_sql("<SUBSIDIARY>", 0, 0, 25000, 0.10))
    print("\n---\n")
    print(drivers_sql("<SUBSIDIARY>", [0, 0], ["<ACCT1>", "<ACCT2>"]))
    print("\n---\n")
    print(drivers_by_id_sql([0, 0], [0, 0], with_grounding=True))
    print("\n---\n")
    print(account_history_sql([0, 0], [0, 0], by_entity=True))
