# finance-automation-lab

A public portfolio of AI-powered finance automations on NetSuite, built in public. Each build pairs
a **deterministic calculation layer** with a **thin AI layer**, wrapped in **audit-grade controls**.

The one rule everything follows: **right-size the AI.** Deterministic code (or native NetSuite
config) does anything that must be calculated, matched, or audited. The LLM is used only to (a) turn
messy input into structure and (b) explain results in words. A deterministic check then verifies the
AI never changed a number. *AI drafts, code checks, human approves.*

> All data here is **synthetic or genericised**. No real company names, account numbers, GL codes,
> or field IDs. Live figures from any connected system are handled transiently and never committed.

---

## Build 1 — Flux (variance) review automation

A month-end flux review: detect material account movements, explain the drivers from the underlying
transactions, and produce a report + email draft — without an LLM ever touching a number.

### The right-size split

| Step | Owner | Why |
|------|-------|-----|
| Variance, per subsidiary & account (periodic-over-periodic) | **NetSuite saved search** | Deterministic, finance-owned, no developer needed |
| Tolerance / materiality flag | **Code** (`ns_flux_sql.flag_reviews`) | Versioned + unit-tested, not buried in a formula |
| Filter to the flagged accounts | **Code** | A filter, not a judgement |
| Pull + pre-aggregate driver transactions (+ memos/dimensions) | **SuiteQL `GROUP BY`** | Auditable retrieval |
| Decompose the movement by vendor (new / dropped / increased / decreased) | **Code** (`vendor_bridge`) | The arithmetic of "who moved" is deterministic |
| Trend / recurrence / SPLY / YTD / common-size / confidence / sensitivity | **Code** | Comparison facts are computed, never asserted by the AI |
| Explain each movement in plain English | **AI** | The only AI step |
| Verify every number + vendor in the explanation | **Code (the eval)** | The audit seam |
| Assemble report + email draft | **Code** | Numbers never come from the AI |

### Components

| File | Layer | Touches a number? |
|------|-------|-------------------|
| `Week1/ns_flux_sql.py` | genericised SuiteQL (flux + grounded drivers + trailing history) + the tolerance gate + derived comparison facts (trend / YTD / common-size / confidence / sensitivity) | yes (in NetSuite / the gate / the facts) |
| `Week1/eval_check.py` | number-match seam | checks only |
| `Week1/ns_flux_eval.py` | transaction-level number + provenance eval | checks only |
| `Week1/ns_flux_report.py` | deterministic report assembler | formats only |
| `Week1/flux_routine_playbook.md` | the scheduled-automation playbook | — |

The pandas reference engine, the offline demo, and the test suites are kept in a local
`Week1/working/` dev set (not tracked here).

### The audit seam

When the AI explains a flagged account from its driver transactions, two deterministic checks guard
the narrative before it can reach a report or email:

1. **Number-match** — every figure must trace to the account facts, a pulled transaction amount, or a
   code-computed comparison fact (trend / SPLY / YTD).
2. **Provenance** — the narrative may only name vendors that appear in the pulled transactions.

If no transaction explains a movement, the AI must say so rather than invent a cause. The *why* is
grounded in pulled memos/dimensions and the computed trend facts; operational context that is not in
NetSuite (a sales kickoff, a head-count, "expected to normalise") may appear **only** as a
clearly-labelled *Assumption (unverified)*, outside the eval — never asserted as fact. An unverified
narrative is never shipped.

### Tests

The runtime modules are covered by 44 tests kept in the local `Week1/working/` dev set
(`test_flux.py`, `test_ns_flux_eval.py`, `test_ns_flux_pipeline.py`). They add `Week1/` to the path
and run from `Week1/working/`.

### Build vs buy

NetSuite's native **GenAI Flux Analysis** (2026.1, in Account Reconciliation — part of the
**separately-licensed EPM** suite) does the same *shape* of thing: detect material fluctuations by
configurable threshold, draft a plain-language narrative (the Autonomous Close *flux monitor* adds
root-cause diagnosis). If you are on EPM and its thresholds fit, buy it.

You build your own when you need to **own the calculation line by line, set your own thresholds, and —
above all — own the eval and the audit trail.** The native agent's threshold is configurable but its
calculation, model, and narrative are a black box; it does not advertise a deterministic "every figure
traces to source" check. For Audit-Committee material — the audience that most needs traceability —
that check is the whole point, and it is exactly what this build keeps in code. (For a supported path
to drive this from Claude on-platform, 2026.1 also ships the **AI Connector Service** for NetSuite
Analytics Warehouse.)

A fuller **four-way comparison** — this build vs full-AI vs embedded EPM vs embedded EPM-AI, with a
capability matrix and cost-benefit — is in
[Week1/flux_approaches_comparison.md](Week1/flux_approaches_comparison.md).

---

## Build 2 — Manual JE anomaly reviewer (detective control + maker-checker)

An AI **detective control** over a manual journal-entry register: deterministic rules flag the
entries a controller should actually look at, an AI reviewer writes the note on the ambiguous ones,
and a **second AI agent challenges it** — segregation of duties, for agents. No LLM ever computes a
figure or decides a disposition.

### The right-size split

| Step | Owner | Why |
|------|-------|-----|
| Flag anomalies (10 rules) + risk score + tier | **Code** ([Week3/je_rules.py](Week3/je_rules.py)) | "Posted on a Saturday?", "preparer == approver?", "duplicate amount?" are exact tests — versioned + unit-tested, never sent to an LLM |
| Decide who must review (disposition) | **Code** | High-severity / score ≥ 5 auto-escalates regardless of the AI |
| Judge the grey-zone (medium) cases + write a reviewer note | **AI — reviewer** (Haiku) | Plain-English judgement is the one thing rules can't own |
| Challenge the reviewer (false positives + missed risk) | **AI — challenger** (Sonnet) | Four-eyes; can only make an entry *more* scrutinised, never less |
| Verify every figure in the note traces to the entry | **Code (the guard)** | The audit seam — an invented number is rejected |
| Assemble the reviewer worklist | **Code** ([Week3/je_report.py](Week3/je_report.py)) | Numbers never come from the AI |

### Components

| File | Layer | Touches a number? |
|------|-------|-------------------|
| [Week3/je_rules.py](Week3/je_rules.py) | 10 pure, tested rules + deterministic risk score/tier | yes (in the rules) |
| [Week3/je_review.py](Week3/je_review.py) | reviewer + challenger subagents (`template`/`llm` modes) + the number-trace guard | guard checks only |
| [Week3/je_report.py](Week3/je_report.py) | deterministic worklist assembler | formats only |
| [Week3/skills/je-reviewer/SKILL.md](Week3/skills/je-reviewer/SKILL.md) | the reusable **Agent Skill** (progressive disclosure → [rules_reference.md](Week3/skills/je-reviewer/rules_reference.md)) | — |

The synthetic register (~10 planted anomalies), the offline demo, and the test suites live in a
local `Week3/working/` dev set (not tracked here).

### The rules

`over_threshold · round_thousand · off_hours (weekend/holiday/after-hours) · weak_description ·
no_support · sensitive_account (manual JE to a control/bank/equity account) · entry_post_gap ·
closed_period · sod_breach (preparer = approver / unapproved) · near_duplicate`. Thresholds are
policy, set on `RuleContext`, not buried in a formula. See
[rules_reference.md](Week3/skills/je-reviewer/rules_reference.md).

### The maker-checker seam

The reviewer AI drafts a note only from the entry's own facts + the fired flags; a deterministic
**number-trace guard** then rejects any figure it cannot trace back to the entry. The challenger AI
re-reads the same facts and the note, looking specifically for over-flagging and — the harder task —
*missed* risk. **Code has the last word:** a `missed_risk` challenge forces escalation; the AI can
never wave a high-severity flag through.

### Tests

Two plain-assert suites in the local `Week3/working/` dev set: `test_je_rules.py` (12) and
`test_je_review.py` (9) — **21 tests**. The headline check: all **10 planted anomalies caught, 0
false positives** on the clean rows.

### Build vs buy

NetSuite 2026.1 improved JE **approval workflow** (Suite Approvals — next-approver, aging,
lock/reopen), but that is a *preventive* approval control, not an **AI detective review** for
anomalies. *Verdict:* complementary — this build closes the documented manual-JE control gap with a
worklist a human works top-down, plus a maker-checker decision trail an auditor can follow.

### NetSuite-native build (SuiteScript + `N/llm`)

The same detective control, ported to run **entirely inside NetSuite**: the rule engine and the
number-trace guard as SuiteScript, the reviewer note and the challenger critique from the embedded
**`N/llm`** model (OCI Generative AI), emailed to a reviewer as a DRAFT and saved to the File Cabinet
— no external orchestrator, no data leaving the platform. It keeps the same right-size rule and the
same maker-checker seam (a `missed_risk` challenge still forces escalation; an invented figure is
still rejected in code). The rules + guard are covered by **19 off-platform Jest tests** with the same
"all planted anomalies caught, 0 false positives" headline. **Deployed and run live in a sandbox**, it
produced **byte-identical** output to the Python hybrid on the same period (Jun 2026: 2 journals, 0
escalate, 0 guard failures) — *same control, different runtime.* This is the in-platform sibling of the
Python build above, exactly as [Week1/suitescript-flux/](Week1/suitescript-flux/) is for Build 1.
See [Week3/suitescript-je-review/](Week3/suitescript-je-review/) (and its
[DEPLOY.md](Week3/suitescript-je-review/DEPLOY.md)).

A fuller **approaches comparison** — hybrid (this build) vs full-AI vs embedded SuiteScript `N/llm`,
why there is **no native NetSuite detective control** for this, an honest read on *when Full AI is
actually better*, and the SuiteQL-vs-saved-search retrieval choice — is in
[Week3/je_approaches_comparison.md](Week3/je_approaches_comparison.md).
