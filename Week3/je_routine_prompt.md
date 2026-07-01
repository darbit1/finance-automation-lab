# Manual JE anomaly review routine — the prompt

This is the canonical instruction for the scheduled **Claude Routine** (the hybrid, option 1). It is
kept here, in the repo, so the AI step is documented and version-controlled (per CLAUDE.md). **The live
copy lives in the claude.ai Routine's message field — paste this text there; editing it here alone
changes nothing.**

The deterministic work is committed Python in `Week3/` (`je_rules`, `je_review`, `je_report`). You only
(a) pull the register via the NetSuite connector, (b) call those functions via Bash, and (c) write the
grey-zone reviewer note + the challenger critique. Every figure in a note is checked by code before
anything is drafted, and **code has the last word on disposition**. AI drafts, code checks, human
approves. **Draft only — never send, never post, never approve or reverse an entry.**

Set per run (from the Routine config): `<PERIOD_IDS>` (or leave blank = most recent month with manual
journals), `<ACCOUNTING_BOOK>` (default 1), `<APPROVAL_THRESHOLD>` (default 50000),
`<ENABLE_APPROVER_RULES>` (**false where the account runs no JE approval workflow**), `<RECIPIENT>`.

**Setup — make the modules importable (before any Python).** The committed modules live in the repo's
`Week3/` directory and the repo root is your initial working directory. Either run helpers with
`PYTHONPATH=Week3 python <script>`, or begin every script with `import sys; sys.path.insert(0, "Week3")`.
If you write a helper into a scratchpad/temp folder, use the **absolute** repo path
(`sys.path.insert(0, "<repo_root>/Week3")` — get `<repo_root>` from `pwd`). Sanity-check first:
`python -c "import sys; sys.path.insert(0,'Week3'); import je_rules, je_review, je_report; print('modules ok')"`.

---

## Steps

1. **Periods.** Run the periods query with NetSuite `ns_runCustomSuiteQL` (recent monthly periods,
   newest first, each with the native `closed`/`alllocked` flag — the same SQL as
   `suitescript-je-review/.../je_sql.js recentPeriodsSql`). If `<PERIOD_IDS>` is blank, pick the most
   recent period that actually has manual journals (a quick `COUNT(DISTINCT id) … type='Journal'`
   grouped by `postingperiod`). Record which period ids are closed/locked → `closed_periods`.

2. **Register.** For the in-scope period(s), run three read-only queries via `ns_runCustomSuiteQL`
   (mirror the `je_sql.js` builders):
   - **headers** — one row per manual `Journal` (id, tranid, trandate, `createddate`, postingperiod,
     `BUILTIN.DF(createdby)` preparer, the approver column, memo, total debits).
   - **timestamps** — `TO_CHAR(createddate,'YYYY-MM-DD HH24:MI:SS')` for those ids (the header returns
     date-only; the **time** is what `off_hours` needs — don't skip this).
   - **lines** — account + `accttype` + amount per journal, to pick the representative account.
   Retrieval is read-only. Keep the pulled figures **transient** — never write real ledger data into
   the repo.

3. **Assemble.** Build a `list[je_rules.JournalEntry]`: `post_ts` from the precise timestamp;
   `account`/`account_type` from the **representative line** (a sensitive control/bank/equity line wins,
   else the largest by |amount|; map `accttype`→category as in `je_rules.normalizeAcctType`);
   `amount` = total debits; `has_support` = your support field if wired, else default true; `approver` =
   "" when none. Then
   `ctx = je_rules.RuleContext(register=register, closed_periods=frozenset(closed_ids),
   approval_threshold=<APPROVAL_THRESHOLD>, enable_approver_rules=<ENABLE_APPROVER_RULES>)`.

4. **Assess (all in code — no judgement by you here).**
   `assessments = je_rules.assess_register(register, ctx)`. This produces, per entry, the fired flags,
   the risk score, and the tier. **Do not add, drop, or re-weight a flag** — the rules are the control.

5. **Maker-checker.** For each assessment:
   - **tier `clear` or `low`:** accept deterministically — `r = je_review.run_maker_checker(a,
     mode="template")` (no AI; keeps token cost and noise down).
   - **tier `medium` or `high` (the grey zone — the ONLY AI step):** *you* write the two notes, grounded
     **only** in that entry's facts + its fired flags (never a figure or control not present):
     - **Reviewer** → `je_review.ReviewNote(je_id, residual_risk, note, recommended_action,
       model="claude-haiku-4-5-20251001")`. **If any flag is high-severity, `residual_risk` MUST be
       `"escalate"`** (code guard-rail, not your discretion). A 3-sentences-max note.
     - **Challenger** → `je_review.Challenge(je_id, verdict, rationale, model="claude-sonnet-5")`.
       Look specifically for a **false positive** (over-flagged noise) and, the harder task, a **missed
       risk** — if the reviewer under-called a high-severity flag, return `verdict="missed_risk"`.
     - **Guard (code gate):** `passed, offenders = je_review.guard_note(note, a)`. If it fails, the note
       cited an untraceable figure — **do not patch the number to pass**; keep `passed=False` (the
       worklist shows the warning and the note is not relied upon).
     - Wrap: `r = je_review.MakerCheckerResult(assessment=a, review=note, challenge=challenge,
       note_guard_passed=passed)`. (`final_disposition` is computed by code: `missed_risk`→escalate;
       `false_positive` can only soften an over-escalation to monitor.)
   Collect the `r` objects in register order.

6. **Assemble + draft.** `wl = je_report.build_worklist(results)` (markdown, most-risky first) and
   `summ = je_report.summarise(results)`. Write `wl` to `out/je_review_<period>.md`. Create a Gmail
   draft to `<RECIPIENT>` — `subject = "Manual JE anomaly review — <period> — {summ['escalate']} to
   escalate"`, body = `wl`. **Draft only.**

7. **Summary.** Print: period(s) used, entries assessed, escalate / monitor / accept counts,
   challenger overrides, guard failures, draft id.

**On any failure** (connector down, query error): do not ship a partial worklist. Draft to
`<RECIPIENT>` with subject `Manual JE anomaly review - FAILED - <date>` and one paragraph on what
failed, then stop.

## Model
The two notes are short judgement over a small structured fact block, so **Haiku** meets the bar for the
reviewer; the challenger reasons about *missed* risk (harder) → **Sonnet**. The deterministic steps
(rules, score, guard, report) cost zero model tokens and run identically every time.
