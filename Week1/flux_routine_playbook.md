# Flux automation — Routine playbook

The instruction set the scheduled Claude Routine runs each month. Deterministic work is done by
committed code/SuiteQL; the AI only turns flagged transactions into plain-language explanations;
a deterministic eval guards every explanation before anything is drafted. **AI drafts, code
checks, human approves.**

## Run config (set in the Routine, not committed)
- `<SAVED_SEARCH_ID>` — the trial-balance saved search to run (returns Classification, Account Type,
  Account = internal id, Month - 1 = current, Month - 2 = prior, Formula = difference). It is the
  single source of the calc; it is consolidated and reports on one accounting book.
- `<ACCOUNTING_BOOK>` — the book the saved search reports on. Default `1` (primary). Driver pulls
  MUST use the same book or the variance is over-stated (transactionaccountingline has one row per
  book).
- `<ABS_THRESHOLD>` / `<PCT_THRESHOLD>` — tolerance gate. Default `25000` / `0.10`. (The saved
  search returns the difference but NO tolerance flag, so the gate is applied in code.)
- `<FINANCE_LIST>` — Gmail draft recipient. **Draft only; never send.**
- Model: use an economical model (Haiku-class) for the explanation step — it is extract-and-
  summarise over a tiny pre-aggregated table, not reasoning-heavy. (Documented per CLAUDE.md.)

## Cadence
Monthly, a few working days into the new month (after close). **Current = the just-closed month;
Prior = the month before.** Resolve names → IDs with `ns_flux_sql.period_lookup_sql(...)`.

## Steps (each run)
1. **Resolve periods.** From the run date, current = the just-closed month (month before the run
   month), prior = the month before that. Resolve both names to internal IDs with
   `ns_flux_sql.period_lookup_sql(current_name, prior_name)` via the NetSuite SuiteQL tool. Abort
   (FAILURE) if either is missing.
2. **Run the saved search.** `ns_runSavedSearch(searchId=<SAVED_SEARCH_ID>)`, paging with
   `range_start`/`range_end` (e.g. 0-50, 50-250, ...) until it returns an empty page. Each row has:
   `Classification`, `Account Type`, `Account` (= account **internal id**), `Month - 1` (current),
   `Month - 2` (prior), `Formula (Numeric)` (= difference). It is consolidated, single book.
   *Token saver:* if the saved search adds a criteria to return only material movers (e.g.
   `|Formula| >= <ABS_THRESHOLD>` and exclude rows where Month-1 = Month-2), it returns a handful
   of rows instead of the whole trial balance — far fewer tokens. The in-code gate (step 3) still
   applies as the authoritative check.
3. **Apply the tolerance gate (in code — the search has no flag).** For each row: prior = Month-2,
   current = Month-1, variance = current − prior, pct = None if prior == 0 else variance/abs(prior).
   Flag **REVIEW** if `abs(variance) >= <ABS_THRESHOLD>` AND (`prior == 0` OR `abs(pct) >= <PCT_THRESHOLD>`).
   Record the count of within-tolerance rows. If zero REVIEW → assemble a one-line "all within
   tolerance" report, draft it (step 8), stop.
4. **Pull drivers.** For the REVIEW account internal ids, run
   `ns_flux_sql.drivers_by_id_sql(account_ids, [curr_id, prior_id], <ACCOUNTING_BOOK>)` via the
   NetSuite SuiteQL tool. **Same book as the saved search** (else the variance is over-stated). This
   pre-aggregated table (by period / subsidiary / type / vendor, with `tranid`) is the ONLY
   transaction context the AI sees. Flag any test/one-off `tranid` as a reviewer note.
5. **Explain (AI).** For each REVIEW account, write ONE plain-language paragraph using **only**:
   the account's facts (prior, current, variance, %) and its driver rows. Rules:
   - Use only numbers present in those facts/drivers. Introduce no other figure.
   - Name only vendors/entities present in the driver rows.
   - If no driver explains the swing (e.g. journals with no vendor, or the swing sits in the prior
     period), write: *"driver not determinable from current transactions — refer to <prior period>
     journals."* Do **not** invent a cause.
6. **Check (deterministic eval).** Run `ns_flux_eval.check_explanation(narrative, fact, drivers)`
   for each. If it returns not-ok, set that account's `eval_ok = False` (its narrative is withheld
   in the report). Never ship an unverified narrative.
7. **Assemble the email in code (one call).** `email = ns_flux_report.build_email(meta, review_rows,
   ok_count, notes)` returns `{subject, body (markdown), html}`. Pass `notes` any reviewer notes —
   **anything containing digits (a `tranid`, a journal id like `JE164589`) goes in `notes`, NOT in a
   narrative**, because the eval treats stray digits as invented figures. Write `email["body"]` to
   the report file (`out/flux_<SUBSIDIARY>_<current>.md`). Do NOT hand-write HTML in the draft call —
   `build_email` produces it (a token saver).
8. **Draft email.** Create a Gmail **draft** to `<FINANCE_LIST>` with `subject=email["subject"]`,
   `body=email["body"]`, `html_body=email["html"]`. **Never send.** A human reviews and sends.
9. **On any failure** (NetSuite/Gmail connector unavailable, query error): stop, and draft/log a
   short failure notice to `<FINANCE_LIST>` instead of a partial report. Send nothing half-formed.

## Token efficiency (right-size the context, not just the AI)
- **Return only flagged rows.** For the SuiteQL fallback use `flux_sql(..., review_only=True)`; for
  the saved search add a material-mover criteria (step 2). A trial balance is mostly flat — pulling
  all of it into context is the biggest avoidable cost.
- **Pre-aggregate drivers** (step 4) — the AI sees a few ranked rows, never raw transaction lines.
- **Assemble the email in code** (`build_email`) — no hand-written HTML in tool calls.
- **Cheapest model that meets the bar** for the explain step (Haiku-class): it is extract-and-
  summarise over a tiny table.
- The deterministic steps (calc, eval, report) cost **zero** model tokens — keep them in code.

## What is code vs AI (the right-size guarantee)
| Step | Owner |
|---|---|
| Flux calc + tolerance (2) | NetSuite saved search / SuiteQL — deterministic |
| Filter REVIEW (3) | Code — a filter |
| Driver pre-aggregation (4) | SuiteQL `GROUP BY` — deterministic |
| Explanation (5) | **AI** — the only AI step |
| Number + provenance check (6) | `ns_flux_eval` — deterministic |
| Report + draft assembly (7–8) | Code — deterministic; numbers never come from the AI |

## Known caveat
The Routine runs headless in the cloud. It must inherit the NetSuite + Gmail connectors. The first
scheduled run is the real test of that; step 9 ensures a failure is reported, not silently shipped.
If connectors aren't available in the Routine environment, move orchestration to n8n (Week 7) or a
local Python job with Gmail OAuth.
