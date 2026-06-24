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
| Variance, per subsidiary & account | **NetSuite saved search** | Deterministic, finance-owned, no developer needed |
| Tolerance / materiality flag | **Code** (`ns_flux_sql.flag_reviews`) | Versioned + unit-tested, not buried in a formula |
| Filter to the flagged accounts | **Code** | A filter, not a judgement |
| Pull + pre-aggregate driver transactions | **SuiteQL `GROUP BY`** | Auditable retrieval |
| Explain each movement in plain English | **AI** | The only AI step |
| Verify every number + vendor in the explanation | **Code (the eval)** | The audit seam |
| Assemble report + email draft | **Code** | Numbers never come from the AI |

### Components

| File | Layer | Touches a number? |
|------|-------|-------------------|
| `Week1/ns_flux_sql.py` | genericised SuiteQL (flux + drivers) + the tolerance gate | yes (in NetSuite / the gate) |
| `Week1/eval_check.py` | number-match seam | checks only |
| `Week1/ns_flux_eval.py` | transaction-level number + provenance eval | checks only |
| `Week1/ns_flux_report.py` | deterministic report assembler | formats only |
| `Week1/flux_routine_playbook.md` | the scheduled-automation playbook | — |

The pandas reference engine, the offline demo, and the test suites are kept in a local
`Week1/working/` dev set (not tracked here).

### The audit seam

When the AI explains a flagged account from its driver transactions, two deterministic checks guard
the narrative before it can reach a report or email:

1. **Number-match** — every figure must trace to the account facts or a pulled transaction amount.
2. **Provenance** — the narrative may only name vendors that appear in the pulled transactions.

If no transaction explains a movement, the AI must say so rather than invent a cause. An unverified
narrative is never shipped.

### Tests

The runtime modules are covered by 24 tests kept in the local `Week1/working/` dev set
(`test_flux.py`, `test_ns_flux_eval.py`, `test_ns_flux_pipeline.py`). They add `Week1/` to the path
and run from `Week1/working/`.

### Build vs buy

NetSuite's native GenAI Flux (2026.1, EPM) does the same shape of thing: detect by threshold, draft a
narrative. If you are on EPM and the thresholds fit, buy it. You build your own when you need to
control the calculation line by line, set your own thresholds, and own the eval and the audit trail.
