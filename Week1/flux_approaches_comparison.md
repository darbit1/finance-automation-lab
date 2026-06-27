# Flux analysis — four approaches compared (with cost-benefit)

A decision aid for *how* to run a monthly flux (variance) review on NetSuite. The same job — detect
material account movements, explain them, report to finance — can be delivered four ways. They differ
most in **who produces the numbers** and **whether anything verifies them**, which is the axis that
matters when the audience is an Audit or Finance Committee.

> All figures below are qualitative bands (Low / Med / High) or structure, not quotes. NetSuite EPM
> and its GenAI features are separately licensed and priced by negotiation; treat license cost as
> "quote-based, typically significant" rather than a number.

## The four approaches

1. **This build — Python calc + AI description.** NetSuite saved search computes the variance; committed
   Python applies the tolerance gate, pulls grounded drivers, and computes every comparison fact
   (trend, SPLY, YTD, common-size, confidence, sensitivity, vendor bridge). The LLM writes *only* the
   prose; a deterministic eval verifies every figure and vendor before anything ships. Orchestrated by
   a scheduled Claude Routine → Gmail draft. *AI drafts, code checks, human approves.*
2. **Full AI.** A single rich prompt to an LLM via the AI Connector / MCP, pointed at the File Cabinet
   reports (or live data). The model reads the statements and *produces the entire report* — numbers,
   ratios, sensitivity, confidence, narrative — in one pass. No deterministic recompute or check.
3. **Embedded NetSuite EPM (non-AI).** Native NetSuite: Account Reconciliation, Financial Report
   Builder variance columns, saved-search materiality flags, KPI/SuiteAnalytics. Deterministic, mature,
   supported — but the **explanation is written by a human analyst** (no narrative automation).
4. **Embedded NetSuite AI (2026.1 GenAI Flux Analysis).** Native GenAI in EPM Account Reconciliation:
   detect material fluctuations by configurable threshold and auto-draft a plain-language narrative;
   the Autonomous Close *flux monitor* adds root-cause diagnosis. Vendor-built and vendor-maintained.

## Capability comparison

| Dimension | 1. This build (Python + AI) | 2. Full AI | 3. NetSuite EPM (non-AI) | 4. NetSuite AI (GenAI flux) |
|---|---|---|---|---|
| Who computes the numbers | NetSuite + Python | **the LLM** | NetSuite (native) | NetSuite (native) |
| Number integrity ("AI never alters a figure") | **Guaranteed** (eval withholds) | None | Guaranteed (no AI) | Vendor-asserted, not exposed |
| Deterministic verification of the narrative | **Yes** (number + provenance eval) | No | n/a (human writes it) | No published check |
| Reproducibility (same input → same output) | **High** | Low (varies per run) | High | Med (model nondeterminism) |
| Narrative explanations | Automated, grounded in memos/journals/vendors | Automated, ungrounded | **Manual** (analyst time) | Automated |
| Driver grounding (memos, vendor bridge, tranids) | **Deep** (pulled + cited) | Whatever the model infers | Manual drill-down | Model-dependent, opaque |
| Threshold / control ownership | **You** (versioned, unit-tested code) | Prompt-only, fuzzy | You (native config) | Configurable, vendor logic |
| Customization (calc line-by-line, data sources) | **Full** | Prompt-limited | Med (within EPM) | Low (black box) |
| Multi-period / SPLY / YTD / common-size | Yes (computed) | Yes (asserted) | Yes (native) | Yes |
| Cross-subsidiary + multi-book correctness | **Enforced in SQL** | Error-prone | Native | Native |
| Audit trail / maker-checker | **Yes** (draft-never-send + eval log) | No | Partial (native workflow) | Partial |
| Breadth/polish out of the box (5-section board deck) | Med (extensible) | **High** | Med | Med-High |
| Data freshness | Live (SuiteQL) | Snapshot reports or live | Live | Live |

## Cost-benefit

| Factor | 1. This build | 2. Full AI | 3. NetSuite EPM (non-AI) | 4. NetSuite AI |
|---|---|---|---|---|
| Build / setup effort | **High** (one-time dev) | **Low** (write a prompt) | Med-High (impl. + config) | Low (if already on EPM) |
| Time to first value | Days-weeks | Hours | Weeks-months | Days |
| Licensing / prerequisites | Existing NetSuite + Claude sub; **no new license** | Claude sub / AI Connector | **EPM module (quote-based, significant)** | EPM **+** GenAI entitlement; regional limits |
| Per-run compute cost | **Low** (small tables, Haiku-class; deterministic steps = 0 tokens) | **High** (full statements in context, every run) | None (compute) | Bundled in license |
| Maintenance owner & burden | You / engineering (it's code + tests) | You (prompt drift) | Vendor + admin | **Vendor** |
| Error / rework risk (hidden cost) | **Low** (verified) | **High** (silent wrong numbers → re-checking) | Low | Med (black-box trust) |
| Vendor lock-in / portability | **Low** (stdlib Python; swap orchestrator) | Low-Med | High (EPM) | High (EPM + AI) |
| Scales to more entities/accounts | High (just more rows) | Degrades (context limit, cost) | High | High |
| Upgrade/feature roadmap | You own it | Model upgrades | NetSuite releases | NetSuite releases |

## When each one wins

- **This build** — when the output must be **trusted, repeatable, and audit-defensible**, you want to
  own the calculation and thresholds line-by-line, and you're not paying for EPM. Best fit for the
  Audit/Finance-Committee deliverable. Cost is the upfront engineering; payoff is verified numbers and
  near-zero per-run cost.
- **Full AI** — a **fast first draft / exploration** that a human will re-check anyway, or one-off ad
  hoc analysis. Cheapest to stand up; most expensive in trust and rework. Do not ship its numbers
  unchecked to a board.
- **NetSuite EPM (non-AI)** — you're **already licensed for EPM** and accept that analysts write the
  narratives. Mature, supported, deterministic; the cost is the license and the manual write-up time.
- **NetSuite AI (GenAI flux)** — you're **on EPM, the thresholds fit, and you accept a black box**. Least
  effort, vendor-maintained; you give up control of the calculation and an exposed "every figure
  traces to source" check.

## Recommendation

The honest synthesis: **buy the native EPM AI if you're already on EPM and its thresholds satisfy your
auditors; otherwise this build is the better foundation** — it reaches the same board-ready richness
(common-size, sensitivity, confidence, cash-flow/equity sections are all *computable*) while keeping
every number deterministic and every sentence verified, at near-zero per-run cost and no new license.
"Full AI" is a drafting tool, not a control. The differentiator no native or one-shot option advertises
is the deterministic **"the AI never changed a number"** check — and that is exactly what the
Audit-Committee audience these reports target most needs.
