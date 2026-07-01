---
name: je-reviewer
description: >-
  Review a manual journal-entry (JE) register for control anomalies and produce a
  reviewer worklist. Use when asked to review manual journals, run a JE detective
  control, check journal entries for red flags (SoD breaches, closed-period or
  weekend postings, missing support, round-number plugs, duplicates, manual
  entries to control accounts), or perform a maker-checker review of a JE listing.
  Deterministic rules do the flagging; AI only judges the grey-zone cases and a
  second AI agent challenges it. The AI never computes or alters a figure.
---

# Manual JE anomaly reviewer

A **detective control** over a manual journal-entry register. It answers: *which
manual journals should a controller actually look at this month, and why?*

## The one rule this Skill obeys
**Code flags; AI only judges the grey areas; code has the last word.** Every
flag, risk score and disposition is computed by deterministic, unit-tested rules.
The LLM is used only to (a) write a plain-English reviewer note on ambiguous
cases and (b) challenge that note (four-eyes). An AI note that cites a figure not
in the entry's own facts is rejected by a deterministic guard before it is shown.

## When to use
- A month-end / pre-close review of manual journals.
- Any ad-hoc "is this JE listing clean?" request.
- Do **not** use it to *calculate* anything or to approve/post an entry — it
  produces a reviewer worklist for a human, never an accounting action.

## Inputs
A JE register (CSV or list of rows), one manual JE per row, with:
`je_id, entry_date, post_ts, period, account, account_type, amount, dr_cr,
preparer, approver, description, has_support, dimensions`.
`account_type` matters: `control | bank | equity` are subledger/system-owned and
a *manual* entry to them is a red flag. Configure closed periods and holidays in
the `RuleContext`.

## How it runs (pipeline)
1. **`je_rules.assess_register(register, ctx)`** — runs the 10 rules, returns an
   `Assessment` per entry (flags + deterministic `risk_score` + `tier`).
2. **`je_review.run_maker_checker(assessment, mode)`** — reviewer subagent writes
   a note + residual-risk call → deterministic `guard_note` seam → challenger
   subagent critiques it. `mode="template"` is offline/deterministic;
   `mode="llm"` makes the real Anthropic calls (Haiku reviewer, Sonnet
   challenger).
3. **`je_report.build_worklist(results)`** — renders the reviewer worklist,
   most-risky first, with the full decision trail.

## Disposition (code decides, not the AI)
- **Escalate** — any high-severity flag, or risk score ≥ 5. Auto-escalated by
  code regardless of what the reviewer AI says.
- **Monitor** — the medium grey zone; the reviewer AI's judgement lives here.
- **Accept / Logged** — low or clear; recorded, no action.
- The **challenger** can only make an entry *more* scrutinised: a `missed_risk`
  verdict forces escalation; it can never wave real risk through.

## The rules (summary)
`over_threshold · round_thousand · off_hours · weak_description · no_support ·
sensitive_account · entry_post_gap · closed_period · sod_breach · near_duplicate`

For exact thresholds, severities and the finance rationale for each rule, read
[rules_reference.md](rules_reference.md) — load it only when you need to tune a
threshold, explain why a rule fired, or add a rule.

## Guardrails
- Synthetic/sanitised data only in this repo; live figures stay transient.
- The AI must say "insufficient basis" rather than invent a cause; the number
  guard rejects any untraceable figure in a note.
- This Skill never posts, approves, or reverses an entry — output is advisory.
