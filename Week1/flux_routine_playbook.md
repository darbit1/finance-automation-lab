# Flux automation — Routine playbook

The instruction set the scheduled Claude Routine runs each month. Deterministic work is done by
committed code/SuiteQL; the AI only turns flagged transactions into plain-language explanations;
a deterministic eval guards every explanation before anything is drafted. **AI drafts, code
checks, human approves.**

## Run config (set in the Routine, not committed)
- `<SUBSIDIARY>` — the entity to review (e.g. the HQ entity).
- `<ABS_THRESHOLD>` / `<PCT_THRESHOLD>` — tolerance gate. Default `25000` / `0.10`.
- `<FINANCE_LIST>` — Gmail draft recipient. **Draft only; never send.**
- Account scope: P&L (`Income, COGS, Expense, OthIncome, OthExpense`). Drop for full TB.
- Model: use an economical model (Haiku-class) for the explanation step — it is extract-and-
  summarise over a tiny pre-aggregated table, not reasoning-heavy. (Documented per CLAUDE.md.)

## Cadence
Monthly, a few working days into the new month (after close). **Current = the just-closed month;
Prior = the month before.** Resolve names → IDs with `ns_flux_sql.period_lookup_sql(...)`.

## Steps (each run)
1. **Resolve periods.** From the run date, derive current/prior month names; look up their internal
   IDs (`period_lookup_sql`). Abort with a clear message if either is missing.
2. **Run the flux.** Prefer the saved search via `ns_runSavedSearch` (once it exists). Until then,
   run `ns_runCustomSuiteQL(ns_flux_sql.flux_sql(<SUBSIDIARY>, curr_id, prior_id, <ABS>, <PCT>))`.
   Both return identical rows (current, prior, variance, %, direction, within_tolerance).
3. **Filter.** Keep rows where `within_tolerance = 'REVIEW'`. Record the count of `OK` rows.
   If zero REVIEW rows → assemble a one-line "all within tolerance" report, draft it (step 8), stop.
4. **Pull drivers.** For the REVIEW account numbers, run
   `ns_runCustomSuiteQL(ns_flux_sql.drivers_sql(<SUBSIDIARY>, [curr_id, prior_id], acctnumbers))`.
   This is the ONLY transaction context the AI sees (pre-aggregated by period/type/vendor).
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
7. **Assemble report.** `ns_flux_report.build_report(meta, review_rows, ok_count)` → Markdown.
   Write it to the report file (`out/flux_<SUBSIDIARY>_<current>.md`).
8. **Draft email.** Create a Gmail **draft** to `<FINANCE_LIST>`:
   - Subject: `Flux review — <SUBSIDIARY> — <current period>`
   - Body: the report Markdown.
   - **Never send.** A human reviews and sends.
9. **On any failure** (NetSuite/Gmail connector unavailable, query error): stop, and draft/log a
   short failure notice to `<FINANCE_LIST>` instead of a partial report. Send nothing half-formed.

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
