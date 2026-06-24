# Flux review automation — playbook

A monthly flux (variance) review on a NetSuite trial balance: detect the accounts that moved
materially between two periods, explain each movement from its underlying transactions, and produce
a report plus a Gmail **draft** for a human to review and send.

The design rule is **right-size the AI**: the calculation and every check are deterministic (a
NetSuite saved search + committed Python); the model is used only to turn the flagged transactions
into plain-language sentences. A deterministic eval then verifies that explanation before anything
is drafted. **AI drafts, code checks, human approves.**

> All values in this document are placeholders. The live deployment's concrete values (saved search
> id, recipient, thresholds) are set in the Routine config, not here. No client data lives in this repo.

---

## 1. How it is scheduled

It runs as a **Claude Routine** — a scheduled agent that executes in Anthropic's cloud (not on a
local machine), so it fires regardless of whether any laptop is on.

- **Schedule:** cron `0 6 5 * *` → 06:00 UTC on the 5th of each month (≈ 08:00 Amsterdam in summer,
  07:00 in winter; cron is fixed UTC and does not track DST).
- **Each fire**, the cloud agent: (1) clones the GitHub repo so it has the committed Python, (2) has
  the **NetSuite** and **Gmail** connectors attached, (3) follows this playbook.
- **Manage it** (enable/disable, change the time, run now, delete) in the claude.ai Routines UI.

---

## 2. Configuration

Set on the Routine, not committed here:

| Setting | Meaning | Default |
|---------|---------|---------|
| `<SAVED_SEARCH_ID>` | the trial-balance saved search. Grouped **per (subsidiary, account)** and pre-filtered to non-zero movements. Columns: `Subsidiary`, `Subsidiary Internal ID`, `Classification`, `Account Type`, `Account`, `Account Internal ID`, `Month - 1` (current), `Month - 2` (prior), `Difference`. Single book. | — |
| `<ACCOUNTING_BOOK>` | the book the saved search reports on. Driver pulls MUST use the same book, or the variance is over-stated (`transactionaccountingline` has one row per book). | `1` (primary) |
| `<ABS_THRESHOLD>` / `<PCT_THRESHOLD>` | the tolerance gate. The saved search returns the difference but no flag, so the gate is applied in code. | `25000` / `0.10` |
| `<RECIPIENT>` | the Gmail draft recipient. **Draft only; never send.** | — |
| model | the model the agent runs as. The explanation is extract-and-summarise over a tiny table, so an economical (Haiku-class) model is sufficient. | — |

---

## 3. Scripts used

All in `Week1/`, **Python standard library only** (no `pip install` needed). The agent calls these;
the model only writes the narratives.

| Script | Role | Functions the routine calls |
|--------|------|-----------------------------|
| `ns_flux_sql.py` | builds the SuiteQL strings the NetSuite tool executes, and applies the tolerance gate | `period_lookup_sql()` · `flag_reviews(rows, abs, pct)` → `(review_rows, ok_count)` · `drivers_by_id_sql(account_ids, period_ids, book, subsidiary_ids=)` (single-book, scoped, emits `subsidiary_id`) · `flux_sql(review_only=)` (SuiteQL fallback) |
| `ns_flux_eval.py` (+ `eval_check.py`) | the audit seam: number-match + entity provenance | `check_explanation(narrative, fact, drivers)` |
| `ns_flux_report.py` | assembles the report + email **in code** (no hand-written HTML) | `build_email(meta, review_rows, ok_count, notes)` → `{subject, body, html}` |

Supporting material the routine does **not** call is kept **locally in `Week1/working/`** (a dev set,
not tracked in this repo): `flux_engine.py` (pandas cross-check / reference engine), `ai_layer.py`
(offline narrative templates), `synthetic_data.py` + `run_flux_demo.py` (local demo), and the test
suites `test_flux.py` / `test_ns_flux_eval.py` / `test_ns_flux_pipeline.py`. The
`saved_search_flux_recipe.md` UI guide stays in the repo.

---

## 4. How a run executes

The agent orchestrates three kinds of tool: the **NetSuite** connector (`ns_runCustomSuiteQL`,
`ns_runSavedSearch`), the **Gmail** connector (`create_draft`), and **Bash** (to run the committed
Python). One pattern to keep in mind: **a SuiteQL query is *built* by a Python function, then
*executed* by a separate NetSuite tool call** — two steps. The saved search is the exception
(`ns_runSavedSearch` runs it directly).

Worked example: a run on **5 Jul 2026** → current = **Jun 2026**, prior = **May 2026**.

| # | Step | Tool | Script.function | In → Out |
|---|------|------|-----------------|----------|
| 0 | Trigger | platform cron | — | `0 6 5 * *` fires; agent clones the repo, attaches NetSuite + Gmail |
| 1a | Build period query | **Bash** | `ns_flux_sql.period_lookup_sql('Jun 2026','May 2026')` | names → a SuiteQL string |
| 1b | Run it | **NetSuite** `ns_runCustomSuiteQL` | (executes that string) | → `curr_id`, `prior_id` |
| 2 | The calc | **NetSuite** `ns_runSavedSearch(<SAVED_SEARCH_ID>)`, paged | — (the saved search *is* the calc) | → rows **per (subsidiary, account)**, already non-zero, with Subsidiary/Account Internal IDs + `Difference` |
| 3 | Tolerance filter | **Bash** | `ns_flux_sql.flag_reviews(rows, <ABS>, <PCT>)` | → `(review_rows, ok_count)`; each review_row carries prior_amt/current_amt/variance_abs/variance_pct/direction + its subsidiary & account ids |
| 4a | Build driver query | **Bash** | `ns_flux_sql.drivers_by_id_sql([acct_ids],[curr,prior],<BOOK>,subsidiary_ids=[sub_ids])` | flagged ids → a SuiteQL string |
| 4b | Run it | **NetSuite** `ns_runCustomSuiteQL` | (executes that string) | → driver rows with **subsidiary_id**; the caller matches each to its row by (subsidiary_id, account_id) |
| 5 | Explain | **AI — the only AI step** | — | per account: one narrative from its facts + drivers only |
| 6 | Verify | **Bash** | `ns_flux_eval.check_explanation(narrative, fact, drivers)` | → `(ok, bad_numbers, bad_entities)`; set `eval_ok` |
| 7 | Assemble | **Bash** | `ns_flux_report.build_email(meta, review_rows, ok_count, notes)` | → `{subject, body, html}`; write `body` to `out/flux_<period>.md` |
| 8 | Draft | **Gmail** `create_draft` | — | → a draft in Drafts, to `<RECIPIENT>`. **Never sent.** |
| 9 | Summary | print | — | periods used, #REVIEW, #verified, draft id |

So: ask NetSuite for the period ids (1) → run the saved search for the trial balance (2) → Python
filters to the few flagged accounts (3) → ask NetSuite for the transactions behind them (4) → the
**AI writes the reason** (5) → Python checks every number and vendor in it (6) → Python builds the
email (7) → Gmail saves the draft (8). Three NetSuite calls, one Gmail call, one AI step; everything
else is committed Python.

---

## 5. The rules that make it auditable

- **Tolerance gate (step 3).** For each row: `variance = current − prior`; `pct = None if prior==0
  else variance/abs(prior)`. Flag **REVIEW** when `abs(variance) >= <ABS_THRESHOLD>` AND
  (`prior == 0` OR `abs(pct) >= <PCT_THRESHOLD>`). The model never computes this — it is committed,
  tested code (`ns_flux_sql.flag_reviews` / `is_review` / `variance_metrics`).
- **Explanation constraints (step 5).** Each narrative may use **only** the account's facts (prior,
  current, variance, %) and its driver rows. Use no other number; name only vendors present in the
  drivers; if no driver explains the swing (e.g. journals with no vendor, or the swing sits in the
  prior period) write *"driver not determinable from current transactions — refer to <prior period>
  journals"* — do **not** invent a cause. Put any reference that contains digits (a `tranid`, a
  journal id like `JE164589`) in `notes`, **not** in the narrative — the eval treats stray digits as
  invented figures.
- **The eval is the gate (step 6).** `check_explanation` returns not-ok if any figure or vendor is
  not traceable to the facts/drivers. A failing narrative is set `eval_ok = False` and **withheld**
  from the report — an unverified explanation is never shipped.
- **Draft, never send (step 8).** A human reviews and sends.

---

## 6. Token efficiency

A trial balance is mostly flat, so the biggest cost is pulling rows you don't need into context.

- **Return only flagged rows.** Add a material-mover criteria to the saved search (HAVING on the
  summed difference — see `saved_search_flux_recipe.md`), or for the SuiteQL fallback use
  `flux_sql(..., review_only=True)`. Discard flat rows on arrival regardless.
- **Pre-aggregate drivers** (step 4) — the AI sees a few ranked rows, never raw transaction lines.
- **Assemble the email in code** (`build_email`) — no hand-written HTML in tool calls.
- **Cheapest model that meets the bar** for the explain step (Haiku-class).
- The deterministic steps cost **zero** model tokens — keep them in code.

---

## 7. Failure handling & prerequisites

**On any failure** (NetSuite or Gmail connector unavailable, a query error): do **not** ship a
partial report. Create a Gmail draft to `<RECIPIENT>` with subject `Flux review - FAILED - <date>`
and a one-paragraph description of what failed, then stop.

For a run to succeed, four things must hold:
1. The Routine inherits the **NetSuite + Gmail connectors** in the cloud. *(The first scheduled run
   is the real test of this — trigger a manual run to verify ahead of time.)*
2. The **repo** is reachable (public) so the cloud clones the committed Python.
3. The **saved search** `<SAVED_SEARCH_ID>` exists and returns the expected columns.
4. The **connector auth** (NetSuite token, Gmail) is still valid at run time.

If the cloud connectors ever prove unavailable, move orchestration to n8n or a local Python job with
Gmail OAuth — the committed modules (`ns_flux_sql`, `ns_flux_eval`, `ns_flux_report`) are unchanged
either way.
