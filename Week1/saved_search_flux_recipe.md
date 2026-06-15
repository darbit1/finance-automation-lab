# Flux saved search — build recipe (NetSuite UI)

A finance user can build and own this; no code, no developer. It computes period-over-period
variance **and** a within-tolerance flag entirely in the saved search via formula fields. This is
the deterministic calc layer expressed natively (the project's "right-size the AI" rule: code/native
config does the maths, AI never touches a number).

Placeholders to fill in when you build it:
- `<CURRENT_PERIOD>` / `<PRIOR_PERIOD>` — the posting-period **names** as they appear in NetSuite
  (e.g. the latest closed month and the month before).
- `<ABS_THRESHOLD>` / `<PCT_THRESHOLD>` — your materiality gate. Start at `25000` and `0.10` (€25k
  and 10%). **These two numbers are the only knobs a reviewer touches** — edit them in the formula
  to make the search stricter or looser.
- `<SUBSIDIARY>` — optional, if you want one entity only.

> All amounts/entities here are placeholders. Point this at your own data; nothing in this file is
> client data.

---

## 1. Search type
**Transactions → Saved Search → New → Transaction.**

## 2. Criteria (Standard subtab)
- **Posting** is **true** (posted GL only).
- **Posting Period** is **any of** `<CURRENT_PERIOD>`, `<PRIOR_PERIOD>`.
- **Account : Type** is **any of** Income, COGS, Expense, Other Income, Other Expense *(P&L flux;
  drop this filter for a full trial-balance flux)*.
- *(optional)* **Subsidiary** is `<SUBSIDIARY>`.

## 3. Results (Columns subtab)
Grouping by Account makes this a **Summary** search; the derived columns use `SUM(...)` so each row
is one account across both periods. (A formula column can't reference another formula column, so the
%/flag formulas repeat the `SUM(CASE …)` expressions — that's expected.)

| # | Field | Summary type | Formula |
|---|-------|--------------|---------|
| 1 | **Account** | Group | — |
| 2 | **Current** (Formula → Currency) | Sum | `CASE WHEN {postingperiod} = '<CURRENT_PERIOD>' THEN {amount} ELSE 0 END` |
| 3 | **Prior** (Formula → Currency) | Sum | `CASE WHEN {postingperiod} = '<PRIOR_PERIOD>' THEN {amount} ELSE 0 END` |
| 4 | **Variance** (Formula → Currency) | Sum | `(CASE WHEN {postingperiod} = '<CURRENT_PERIOD>' THEN {amount} ELSE 0 END) - (CASE WHEN {postingperiod} = '<PRIOR_PERIOD>' THEN {amount} ELSE 0 END)` |
| 5 | **Variance %** (Formula → Percent) | Sum | `(SUM(CASE WHEN {postingperiod}='<CURRENT_PERIOD>' THEN {amount} ELSE 0 END) - SUM(CASE WHEN {postingperiod}='<PRIOR_PERIOD>' THEN {amount} ELSE 0 END)) / NULLIF(ABS(SUM(CASE WHEN {postingperiod}='<PRIOR_PERIOD>' THEN {amount} ELSE 0 END)), 0)` |
| 6 | **Within tolerance?** (Formula → Text) | (leave blank / Group) | see below |

**Within tolerance? formula (column 6):**
```
CASE
  WHEN ABS( SUM(CASE WHEN {postingperiod}='<CURRENT_PERIOD>' THEN {amount} ELSE 0 END)
          - SUM(CASE WHEN {postingperiod}='<PRIOR_PERIOD>'   THEN {amount} ELSE 0 END) ) >= <ABS_THRESHOLD>
   AND ( SUM(CASE WHEN {postingperiod}='<PRIOR_PERIOD>' THEN {amount} ELSE 0 END) = 0
         OR ABS( ( SUM(CASE WHEN {postingperiod}='<CURRENT_PERIOD>' THEN {amount} ELSE 0 END)
                 - SUM(CASE WHEN {postingperiod}='<PRIOR_PERIOD>'   THEN {amount} ELSE 0 END) )
                 / NULLIF(ABS(SUM(CASE WHEN {postingperiod}='<PRIOR_PERIOD>' THEN {amount} ELSE 0 END)),0)
               ) >= <PCT_THRESHOLD>
       )
  THEN 'REVIEW' ELSE 'OK'
END
```

Logic, in words: **flag REVIEW when the absolute swing is at least `<ABS_THRESHOLD>` AND either the
account is new-from-zero (prior = 0) OR the percentage swing is at least `<PCT_THRESHOLD>`.** The
`NULLIF(... ,0)` is the divide-by-zero guard — a brand-new account (prior = 0) shows a blank % and
still flags on absolute size.

## 4. Sort
Sort by **Variance** descending (largest swings first), or filter the **Within tolerance?** column to
`REVIEW` to show only what needs a look.

---

## 5. The trade-off to keep in mind (this is the build-vs-buy point)
Putting `<ABS_THRESHOLD>` / `<PCT_THRESHOLD>` in the formula means a finance user can change them in
the UI in seconds — **good**. But they are now **not version-controlled and not unit-tested**: two
people can run "the flux" with different gates and not know it, and there is no test asserting the
formula is right. The custom build earns its place exactly where that governance matters — versioned
thresholds, a test suite, and the AI-narrative number-match eval. Native saved search = fast and
owned by finance; custom = controlled and auditable. (That is the Week 2 build-vs-buy post.)

---

## 6. Validation query (SuiteQL — proves the saved search is right)
Run this and confirm it matches the saved-search output **row for row**. It mirrors the formulas
above (current, prior, variance, %, direction, flag) and is the deterministic maker-checker on the
calc layer.

```sql
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
  CASE WHEN ABS(x.current_amt - x.prior_amt) >= <ABS_THRESHOLD>
            AND (x.prior_amt = 0 OR ABS((x.current_amt - x.prior_amt)/ABS(x.prior_amt)) >= <PCT_THRESHOLD>)
       THEN 'REVIEW' ELSE 'OK' END AS within_tolerance
FROM (
  SELECT a.fullname AS account, a.accttype,
    NVL(SUM(CASE WHEN t.postingperiod = <CURRENT_PERIOD_ID> THEN tal.amount END),0) AS current_amt,
    NVL(SUM(CASE WHEN t.postingperiod = <PRIOR_PERIOD_ID>   THEN tal.amount END),0) AS prior_amt
  FROM transactionaccountingline tal
  JOIN transaction t ON t.id = tal.transaction
  JOIN account a ON a.id = tal.account
  JOIN subsidiary s ON s.id = t.subsidiary
  WHERE t.posting = 'T'
    AND s.name = '<SUBSIDIARY>'
    AND t.postingperiod IN (<CURRENT_PERIOD_ID>, <PRIOR_PERIOD_ID>)
    AND a.accttype IN ('Income','COGS','Expense','OthIncome','OthExpense')
  GROUP BY a.fullname, a.accttype
) x
ORDER BY ABS(x.current_amt - x.prior_amt) DESC
```

> SuiteQL uses period **internal IDs** (`<CURRENT_PERIOD_ID>`); the saved-search formula uses period
> **names** (`<CURRENT_PERIOD>`). Find the IDs with:
> `SELECT id, periodname FROM accountingperiod WHERE periodname IN ('<CURRENT_PERIOD>','<PRIOR_PERIOD>')`.
