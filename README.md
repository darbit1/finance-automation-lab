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
