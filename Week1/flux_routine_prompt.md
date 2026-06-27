# Flux review routine — the prompt

This is the canonical instruction for the scheduled **Claude Routine**. It is kept here, in the repo,
so the AI step is documented and version-controlled (per CLAUDE.md). **The live copy lives in the
claude.ai Routine's message field — paste this text there; editing it here alone changes nothing.**

The deterministic work is committed Python in `Week1/` (`ns_flux_sql`, `ns_flux_eval`,
`ns_flux_report`). You only (a) call those functions via Bash and (b) write each account's narrative.
Every figure and vendor in a narrative is checked by code before anything is drafted. **AI drafts,
code checks, human approves. Draft only — never send.**

Set per run (from the Routine config): `<SAVED_SEARCH_ID>` (the trial-balance search),
`<ACCOUNTING_BOOK>` (default 1), `<ABS_THRESHOLD>`/`<PCT_THRESHOLD>` (25000 / 0.10), `<RECIPIENT>`,
`<HISTORY_MONTHS>` (default 12).

**Setup — make the modules importable (do this before any Python).** The committed modules live in the
repo's `Week1/` directory and the repo root is your initial working directory. Either run helpers from
the repo root with `PYTHONPATH=Week1 python <script>`, or begin every script with
`import sys; sys.path.insert(0, "Week1")`. If you write a helper into a scratchpad/temp folder, that
relative path won't resolve — use the **absolute** repo path: `sys.path.insert(0, "<repo_root>/Week1")`
(get `<repo_root>` from `pwd` at the start). Sanity-check first, from the repo root:
`python -c "import sys; sys.path.insert(0,'Week1'); import ns_flux_sql, ns_flux_eval, ns_flux_report; print('modules ok')"`.

---

## Steps

1. **Periods.** Build `ns_flux_sql.period_lookup_sql(<current>, <prior>, <SPLY>, <trailing months…>)`
   and run it with NetSuite `ns_runCustomSuiteQL` to get the period ids. Current = the month before the
   run; prior = the month before that; SPLY = same month last year; trailing = the last `<HISTORY_MONTHS>`.

2. **Trial balance.** Run `ns_runSavedSearch(<SAVED_SEARCH_ID>)` (paged). Keep the rows **as-is**.

3. **Flag.** `reviews, ok = ns_flux_sql.flag_reviews(rows, <ABS_THRESHOLD>, <PCT_THRESHOLD>)`. Pass the
   **raw** rows — do not rebuild them — so `Subsidiary*`, `Classification`, `Account Type`,
   `Department`, `Class`, and the YTD columns survive onto each review_row. The gate runs on the
   Periodic columns and captures `ytd_amount` from the search.

4. **Drivers (grounded).** Build
   `ns_flux_sql.drivers_by_id_sql([account_ids], [current_id, prior_id], <ACCOUNTING_BOOK>,
   subsidiary_ids=[sub_ids], with_grounding=True)`, run it with `ns_runCustomSuiteQL`, then cap to the
   material few with `ns_flux_sql.top_drivers(rows, 8)`. Match each driver row to its review_row by
   `(subsidiary_id, account_id)`. Set each review_row's **account label to the driver's full
   `account` name only** — do NOT append Classification or Account Type.

5. **History + comparison facts (all in code — no arithmetic by you):**
   - `account_history_sql([account_ids], [trailing+SPLY ids], <ACCOUNTING_BOOK>, subsidiary_ids=[…],
     by_entity=True)` → run it; then per account `ns_flux_sql.trend_facts(history, account_id,
     ordered_period_ids, subsidiary_id=…, sply_period_id=…)`. Attach `sply_amount` + the trend dict.
   - `ns_flux_sql.vendor_bridge(drivers, account_id, current_id, prior_id, subsidiary_id=…)` →
     the per-vendor decomposition (new / dropped / increased / decreased).
   - `ns_flux_sql.common_size_by_classification(reviews, rows)`, `confidence_score(row, drivers,
     trend)`, `sensitivity(row)` → attach `common_size_pct`, `confidence`, `sensitivity`.

6. **Explain — the only AI step.** For each flagged account write ONE narrative that a finance
   reviewer would find genuinely useful. Use, and only use:
   - the account facts (prior, current, variance, %), the driver **memos / line descriptions /
     department / class**, the **`vendor_bridge`**, and the **trend facts**.
   - **Cite the specific source document** — the journal id or bill name (`tranid`) and its amount,
     e.g. "posted via journal JE164589" or "bill 'IS TEST TRIAL BALANCE 1' from Satakerta Rödl Partner
     Oy". Pass those tranids to the eval as `allowed_refs`.
   - **Decompose by vendor** when more than one vendor moved: "net +EUR 25,000 — new vendor B
     +EUR 75,000, partly offset by vendor A down EUR 50,000" (straight from `vendor_bridge`).
   - **Recurring accruals (the "cleared" tax/accrual rows):** do **not** punt. Explain as timing and
     mark recurring — e.g. "Recurring monthly CIT accrual; April posted EUR 28,027 via journal
     JE164569; no May accrual yet — timing, expected at close (third consecutive month per trend)."
   - **Forward-looking / operational context** that is NOT in NetSuite (a head-count, an event,
     "expected to normalise" beyond what trend shows) goes in `assumptions`, **not** the narrative.
   - Only write *"driver not determinable from current transactions — refer to <prior> journals"* as a
     true last resort: no driver in **either** period AND no memo. This should now be rare.

7. **Verify (code gate).** `ok, bad_n, bad_e = ns_flux_eval.check_explanation(narrative, fact, drivers,
   extra_facts={**trend, **{f"{b['entity']}_delta": b['delta'] for b in bridge}}, allowed_refs=refs)`
   where `refs` = the cited drivers' **tranids + memos** (`txn_memo`/`line_memo`) — a memo like
   "2026 Q1 Current tax" carries digits, so it must be whitelisted or its year trips the number check.
   Set `eval_ok = ok`. A failing narrative is withheld by the report — never patch the numbers to pass.

8. **Assemble + draft.** `email = ns_flux_report.build_email(meta, reviews, ok_count, notes=…)`. Write
   `email["body"]` to `out/flux_<period>.md`. Create a Gmail draft to `<RECIPIENT>` with
   `subject=email["subject"]`, body `email["body"]`, html `email["html"]`. **Draft only.**

9. **Summary.** Print: periods used, #REVIEW, #verified, draft id.

**On any failure** (connector down, query error): do not ship a partial report. Draft to
`<RECIPIENT>` with subject `Flux review - FAILED - <date>` and one paragraph on what failed, then stop.

## Model
The explain step is extract-and-summarise over a small structured table, so an economical
(Haiku-class) model meets the bar. The deterministic steps cost zero model tokens.
