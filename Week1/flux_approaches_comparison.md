# Flux analysis — four approaches compared (with cost-benefit)

A decision aid for *how* to run a monthly flux (variance) review on NetSuite. The same job — detect
material account movements, explain them, report to finance — can be delivered four ways. They differ
most in **who produces the numbers**, **whether anything verifies them**, and **where the AI runs**.

> All cost figures are qualitative bands (Low / Med / High), not quotes. NetSuite EPM, its GenAI
> features, and OCI Generative AI overage are priced by negotiation/metering; treat license cost as
> "quote-based" rather than a number.

## The four approaches

1. **This build — external Python calc + Claude narrative.** A NetSuite saved search computes the
   variance; committed, unit-tested Python applies the tolerance gate, pulls grounded drivers, and
   computes every comparison fact (trend, SPLY, YTD, common-size, confidence, sensitivity, vendor
   bridge). A frontier **Claude** model writes *only* the prose; a deterministic eval verifies every
   figure and vendor before anything ships. Orchestrated by a scheduled Claude Routine → Gmail draft.
   *AI drafts, code checks, human approves.*
2. **Full AI.** One rich prompt to an LLM (via the AI Connector / MCP) pointed at the File Cabinet
   reports or live data. The model reads the statements and *produces the whole report* — numbers,
   ratios, sensitivity, confidence, narrative — in one pass. No deterministic recompute or check.
3. **Embedded NetSuite EPM.** The EPM suite (Account Reconciliation, Financial Report Builder variance
   columns, Narrative Insights) — including the **2026.1 GenAI Flux Analysis** that detects by
   configurable threshold and auto-drafts a narrative, plus the Autonomous Close *flux monitor*.
   Vendor-built and vendor-maintained; separately licensed.
4. **Embedded NetSuite AI via SuiteScript (`N/llm`).** Build the solution *entirely inside NetSuite*:
   a Scheduled SuiteScript computes the variance in SuiteQL, then calls the embedded **`N/llm`** module
   (`llm.generateText` / Prompt Studio, with optional RAG + citations) to draft each narrative, and
   emails/stores the result. The LLM runs on **Oracle Cloud Infrastructure (OCI) Generative AI**
   (default **Cohere Command R**; Llama-class also), with a **monthly free-call quota** per account
   (bring-your-own OCI credentials for unlimited, metered). This is the closest sibling to approach 1
   — deterministic calc + LLM narrative — but in-platform and on OCI-tier models. **A working
   implementation of this approach is built in [suitescript-flux/](suitescript-flux/)** (SDF project:
   SuiteQL calc + the ported audit seam + `N/llm` narrative + a scheduled script), with deploy steps.

## Capability comparison

| Dimension | 1. This build (Python + Claude) | 2. Full AI | 3. Embedded EPM | 4. Embedded SuiteScript `N/llm` |
|---|---|---|---|---|
| Who computes the numbers | NetSuite + Python | **the LLM** | NetSuite (native) | **NetSuite (your SuiteScript/SuiteQL)** |
| Number integrity ("AI never alters a figure") | **Guaranteed** (eval withholds) | None | Native calc (AI narrates) | Calc deterministic; **eval is DIY** in SuiteScript |
| Deterministic verification of the narrative | **Yes** (number + provenance eval) | No | No published check | Only if you build it |
| Reproducibility | **High** | Low | Med (calc high, model varies) | Med (calc high, model varies) |
| Narrative quality | **Frontier Claude** | Frontier-class | Vendor model | **OCI Cohere/Llama-class** (lower) |
| Driver grounding (memos, vendor bridge, tranids) | **Deep, cited** | Model-inferred | Opaque | Yes (pass drivers; RAG gives citations) |
| Threshold / control ownership | **You** (versioned, tested code) | Prompt-only | Configurable, vendor logic | **You** (SuiteScript) |
| Customization (calc, data, model) | **Full** (any model) | Prompt-limited | Low (black box) | Full calc; **model limited to OCI catalog** |
| Where data / AI runs | External (NetSuite→Claude API) | External | In NetSuite | **Fully in NetSuite + OCI** (data residency) |
| Multi-period / SPLY / YTD / common-size | Yes (computed) | Yes (asserted) | Yes (native) | Yes (you compute) |
| Cross-subsidiary + multi-book correctness | **Enforced in SQL** | Error-prone | Native | **Enforced in your SQL** |
| Audit trail / maker-checker | **Yes** | No | Partial (native workflow) | DIY + native exec logs |
| Engineering hygiene (git, unit tests) | **High** (44 tests) | None | n/a | Low (SuiteScript; harder to test/version) |
| Breadth/polish out of the box | Med (extensible) | **High** | Med-High | Med (you build) |

## Cost-benefit

| Factor | 1. This build | 2. Full AI | 3. Embedded EPM | 4. SuiteScript `N/llm` |
|---|---|---|---|---|
| Build / setup effort | High (one-time dev) | **Low** (a prompt) | Med-High (impl./config) | High (SuiteScript dev) |
| Time to first value | Days-weeks | Hours | Weeks-months | Days-weeks |
| Licensing / prerequisites | Existing NetSuite + Claude sub; **no new license** | Claude / AI Connector | **EPM module (quote-based, significant)** | **Included** in NetSuite (free LLM quota); BYO-OCI beyond it; regional limits |
| Per-run compute cost | **Low** (small tables; deterministic = 0 tokens) | **High** (full statements each run) | Bundled in license | **Low** within quota, then OCI-metered |
| Maintenance owner | Engineering (code + tests) | You (prompt drift) | **Vendor** + admin | NetSuite admin/dev (SuiteScript) |
| Error / rework risk (hidden cost) | **Low** (verified) | **High** (silent wrong numbers) | Low-Med (black-box trust) | Med (no default eval; weaker model) |
| Vendor lock-in / portability | **Low** (stdlib Python; swap orchestrator/model) | Low-Med | High (EPM) | **High** (SuiteScript + OCI; NetSuite-only) |
| Data residency / governance | Data leaves to Claude API | Data leaves | In-platform | **Strongest — stays in Oracle/NetSuite + OCI** |
| Scales to more entities/accounts | High | Degrades (context, cost) | High | High (but 5 concurrent LLM calls) |

## When each one wins

- **This build (1)** — output must be **trusted, repeatable, audit-defensible**; you want the best
  narrative model, to own thresholds line-by-line, a ready-made deterministic eval, and proper
  software engineering (git, tests, portability), without paying for EPM. Best fit for the
  Audit/Finance-Committee deliverable.
- **Full AI (2)** — a **fast first draft / one-off exploration** a human will re-check. Cheapest to
  stand up, most expensive in trust and rework. Don't ship its numbers unchecked to a board.
- **Embedded EPM (3)** — you're **already licensed for EPM** and its native thresholds/black-box
  narrative satisfy your auditors. Least effort if on EPM; you give up calc control and an exposed
  "every figure traces to source" check.
- **SuiteScript `N/llm` (4)** — you want **everything inside NetSuite**: no external connectors,
  strongest **data residency**, native scheduling, and AI cost bundled in the free quota. Accept
  **OCI-tier models** (Cohere/Llama, below frontier Claude) and that you must **build the verification
  layer yourself** in SuiteScript. The natural choice for a NetSuite-only shop that values in-platform
  governance over model quality and tooling.

## Recommendation

Approaches **1 and 4 are the same idea — deterministic calc + LLM narrative — and the real choice is
where it runs and how good the guardrails are.** Pick **4 (SuiteScript `N/llm`)** if in-platform data
residency and zero external moving parts outweigh everything else, and you're willing to accept a
weaker model and to hand-build the number/provenance check. Pick **1 (this build)** when you want the
**best narrative model, a ready deterministic eval, and engineered controls (versioned, unit-tested,
portable)** — the same in-NetSuite calculation, but with a stronger writer and a proven audit seam.

Buy **EPM (3)** if you're already on it and its thresholds fit; use **Full AI (2)** only as a drafting
tool, never as a control. Across all four, the differentiator this build keeps is the deterministic
**"the AI never changed a number"** check — EPM and one-shot AI don't expose it, and the SuiteScript
route only has it if you build it. For the Audit-Committee audience these reports target, that check is
the whole point.
