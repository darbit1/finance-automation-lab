# Manual-JE anomaly review — approaches compared (with cost-benefit)

A decision aid for *how* to run a manual journal-entry detective control on NetSuite: flag the manual
JEs a controller should actually review, judge the ambiguous ones, and produce a worklist with a
decision trail. The approaches differ most in **who decides what is anomalous**, **whether anything
verifies the output**, and **where the AI runs**.

> All cost figures are qualitative bands (Low / Med / High), not quotes. NetSuite GenAI features and
> OCI Generative AI overage are priced by negotiation/metering; treat license cost as "quote-based."

## Is there a native NetSuite option? (the build-vs-buy reality)

**No** — NetSuite has **no embedded AI *detective* control** that scores *posted* manual journals for
anomaly patterns and drafts a reviewer note. What exists is adjacent and solves a *different* problem:

| Native feature | What it is | Why it isn't this |
|---|---|---|
| **Suite Approvals** (2026.1 JE workflow) | *Preventive* approval routing — next-approver, aging, lock/reopen | Gates an entry *before* it posts; does not score *posted* entries for round-dollar / off-hours / duplicate / closed-period risk |
| **Vendor-payment fraud detection** (2026.1) | AI risk-scoring on *payments* | Payments, not journals |
| **Bill Capture duplicate detection** | Duplicate flagging on *AP bills* | Bills, not manual JEs |
| **EPM Account Reconciliation / SuiteAnalytics** | Matching + analytics | Reconciliation/reporting, not a JE-anomaly detective with narrative |

So for *this* control, "buy it from NetSuite" isn't really on the table — the realistic choice is **how
you build it**. That leaves three build approaches:

## The three approaches

1. **This build — external Python rules + Claude maker-checker (hybrid).** Committed, unit-tested
   Python runs **10 deterministic rules** + a risk score/tier over the register (pulled live via the
   NetSuite MCP connector, or from a file). A frontier **Claude** model acts only in the grey zone: a
   **reviewer** (Haiku) writes the note, a **challenger** (Sonnet) critiques it (four-eyes). A
   **number-trace guard** rejects any invented figure, and **code has the last word** (a `missed_risk`
   challenge forces escalation). → [je_rules.py](je_rules.py), [je_review.py](je_review.py).
2. **Full AI.** One rich prompt to an LLM (via the AI Connector / MCP) pointed at the JE register. The
   model reads the entries and *itself decides* which are anomalous, how risky, and writes the notes —
   in one pass. No deterministic rule set, no guaranteed recall, no guard.
3. **Embedded NetSuite AI via SuiteScript (`N/llm`).** The same *hybrid* as #1 built to run **entirely
   inside NetSuite**: a Scheduled SuiteScript runs the rules + guard in code and calls the embedded
   **`N/llm`** model (OCI Generative AI — Cohere Command R / R+) for the reviewer + challenger notes,
   then emails/stores the worklist. → [suitescript-je-review/](suitescript-je-review/) (SDF project;
   **19 off-platform Jest tests**).

## Capability comparison

| Dimension | 1. Hybrid (Python + Claude) | 2. Full AI | 3. Embedded SuiteScript `N/llm` |
|---|---|---|---|
| What decides "anomalous" | **Versioned, tested rules** + AI on the grey zone | **the LLM** (whole register) | **Your SuiteScript rules** + `N/llm` on the grey zone |
| Guaranteed recall on known patterns | **Yes** (rules always fire) | No (may silently miss) | **Yes** (rules always fire) |
| Novel/holistic pattern spotting | Only what a rule encodes (+ reviewer judgment) | **Strongest** (reads everything at once) | Only what a rule encodes (+ note judgment) |
| Number integrity ("AI never invents a figure") | **Guaranteed** (guard) | None | **Guaranteed** (guard ported) |
| Second-agent challenge (four-eyes) | **Yes** | No | **Yes** |
| Reproducibility (same input → same flags) | **High** | Low | **High** |
| Reviewer-note quality | **Frontier Claude** | Frontier-class | OCI Cohere-class (lower) |
| Rule / threshold ownership | **You** (versioned, tested) | Prompt-only | **You** (config + rules) |
| Where data / AI runs | External (NetSuite→Claude API) | External | **Fully in NetSuite + OCI** |
| Cross-entry rules (duplicate/split) | **Yes** (register-aware) | Model-inferred | **Yes** (register-aware) |
| Auditable decision trail | **Yes** (maker-checker result) | No | DIY worklist + native exec logs |
| Engineering hygiene (git, unit tests) | **High** (21 tests) | None | Med — SDF + **19 Jest tests** |
| Cost at register scale | **Low** (rules = 0 tokens; AI only on flagged) | **High** (whole register each run) | **Low** within `N/llm` quota, then OCI-metered |

## Cost-benefit

| Factor | 1. Hybrid | 2. Full AI | 3. SuiteScript `N/llm` |
|---|---|---|---|
| Build / setup effort | High (one-time dev) | **Low** (a prompt) | High (SuiteScript dev) |
| Time to first value | Days-weeks | Hours | Days-weeks |
| Licensing / prerequisites | Existing NetSuite + Claude sub; **no new license** | Claude / AI Connector | **Included** (free `N/llm` quota); BYO-OCI beyond; regional limits |
| Per-run compute cost | **Low** | **High** | **Low** within quota |
| Maintenance owner | Engineering (code + tests) | You (prompt drift) | NetSuite admin/dev (SuiteScript) |
| Error / rework risk (hidden cost) | **Low** (rules + guard) | **High** (silent miss / invented risk) | Low-Med (rules deterministic; weaker model softer on grey-zone) |
| Vendor lock-in / portability | **Low** (stdlib; swap model) | Low-Med | **High** (SuiteScript + OCI; NetSuite-only) |
| Data residency / governance | Data leaves to Claude API | Data leaves | **Strongest — in Oracle/NetSuite + OCI** |

## Could Full AI be better for this analysis? (the honest case both ways)

It's the right question, and the answer isn't a flat "no." **Where Full AI genuinely wins:**

- **Novel / holistic patterns.** Rules only catch what you *thought to encode*. An LLM reading the
  whole register at once can surface things no rule expresses — a cluster of entries that "rhymes," a
  memo whose story contradicts the amounts, a preparer whose entries drift over the month. That is
  real, and a fixed rule set structurally cannot do it.
- **Free-text and cross-entry narrative.** It reads descriptions, relates entries to each other, and
  reasons about intent — exactly the judgment a rule can't own.
- **Zero rule maintenance / adapts to new schemes.** No one has to codify the next trick; you just ask.

**Where it fails *as the control of record*:**

- **Non-deterministic.** The same register can yield different flags on two runs. A control an auditor
  signs off on has to be *reproducible*; "the model felt differently today" is not a control.
- **No guaranteed recall.** It can **silently miss** a textbook anomaly (a manual JE to a control
  account, a closed-period posting). Rules *always* fire on what they cover — that floor is the point.
- **No number integrity.** With nothing like the guard, it can assert a fabricated exposure figure.
- **Not testable / not versioned; cost + context limits at scale; prompt-injection** via memo text.

**The synthesis (why the hybrid is shaped the way it is).** You don't have to choose. The hybrid already
*puts the LLM exactly where it's better* — judging the grey-zone entries the rules flagged but can't
resolve, and challenging itself — while keeping a **deterministic floor** (guaranteed recall on known
patterns) and a **guard** (no invented figures) underneath. The best of the Full-AI idea is a natural
*extension*: add a Full-AI **"wildcard" pass** as a **complementary, advisory** detector for the
open-ended residual — *"what looks off here that our rules don't encode?"* — whose hits become **flags a
human triages**, never the disposition of record. That buys you the novel-pattern upside without
surrendering the recall, reproducibility, and audit trail that make it a *control*. Ship Full AI as a
second opinion; don't ship it as the control.

## The retrieval layer: SuiteQL-in-code vs a saved search

A related "build" decision is how the register is *retrieved*. This build uses **SuiteQL held in code**
([je_sql.js](suitescript-je-review/src/FileCabinet/SuiteScripts/je_review/je_sql.js) /
`ns_runCustomSuiteQL` via MCP), not a NetSuite **saved search** — deliberately, and for the same reason
the rules live in code:

- **Versioned + diffable + testable.** The query is in git, code-reviewed, and feeds unit-tested logic.
  A saved search lives in *account config*: editable in the UI with no git history, so the control can
  drift silently. For an auditable control, the retrieval definition being versioned *is* the point.
- **Portable across surfaces.** The same SQL runs in the SuiteScript build (`N/query`), the Python
  build (via the MCP connector), and off-platform — one definition. A saved search is bound to one
  account by internal id and must be recreated/kept in sync across sandbox↔prod and the two variants.
- **Exact contract + composability.** The rules need precise shapes — per-book `transactionaccountingline`,
  the created *timestamp with time* (drives `off_hours`), the `ROWNUM` period trick, `closed`/`alllocked`
  flags — built programmatically with sanitised id lists. Some of that is awkward or impossible in the
  saved-search UI, and a saved search's columns can change out from under the parser.

**When a saved search is the better choice** (and this repo uses one): when **finance should own the
logic**. Build 1's flux uses a *saved search* for the variance/materiality calc precisely so finance
can tune the threshold with no developer, and see it in the UI/dashboards. The split is deliberate:
**finance-owned policy → saved search; a fixed technical contract feeding versioned control code →
SuiteQL.** They aren't exclusive — the connector even exposes `ns_runSavedSearch` — you'd just trade
git/tests/portability for in-UI ownership.

## Live field note (a NetSuite sandbox, real data via MCP)

Run over **Apr 2026, 16 real manual journals** (all Q1 CIT accruals) pulled read-only through the MCP
SuiteQL tool, deterministic rules + guard in code: **0 escalate · 7 monitor · 9 logged · 0 guard
failures.** Real signals that survived: `over_threshold` on the three large accruals, `near_duplicate`
on two same-account/same-amount pairs (the challenger correctly asks whether either is a split). One
tuning lesson the live data taught: the connected account runs **no JE approval workflow**, so the `sod_breach`
"no approver" branch flagged every entry until switched off — now a config toggle
(`ENABLE_APPROVER_RULES`). This is the honest value of the deterministic layer: it stays quiet on
routine tax accruals and surfaces only the handful worth a glance — and every tweak is a versioned,
testable change, not a prompt re-roll.

## When each one wins

- **Hybrid (1)** — the detective control must be **trusted, repeatable, audit-defensible**, you want
  the best reviewer/challenger model, own the rules line-by-line, and have proper engineering (git,
  tests, portability) without a NetSuite-only footprint. Best fit for the control an auditor asks about.
- **Full AI (2)** — a **fast first-pass triage / exploratory second opinion** a human re-checks, or the
  **wildcard layer** on top of the rules. Cheapest to stand up; most expensive in trust. Never the
  control of record on its own.
- **SuiteScript `N/llm` (3)** — you want **everything inside NetSuite**: no external connectors,
  strongest data residency, native scheduling, AI cost bundled in the free quota. Same rules + guard +
  challenger, on OCI-tier models (softer grey-zone prose, identical control strength because code holds
  the last word).

## Recommendation

There is **no native NetSuite detective control** for manual-JE anomalies, so this is a *build*
decision, not build-vs-buy. Approaches **1 and 3 are the same idea** — deterministic rules + an LLM
maker-checker with code holding the last word — differing only in *where they run* and *model quality*:
pick **3** for in-platform data residency and zero external moving parts; pick **1** for the sharper
reviewer/challenger and richer packaging. Treat **Full AI (2)** as a **complement, not a substitute**:
it is genuinely better at *novel, holistic* pattern-spotting, so run it as an advisory wildcard pass
whose hits a human triages — but keep the deterministic rules + guard as the auditable floor, because
recall, reproducibility, and "the AI never invented a figure" are exactly what make this a control.
