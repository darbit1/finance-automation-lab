# SuiteScript manual-JE anomaly reviewer (embedded `N/llm`)

A NetSuite-native version of the Week 3 detective control: the deterministic **rule engine** (10 rules
+ risk score) and the **number-trace audit seam** run as SuiteScript inside NetSuite, the **reviewer
note and the challenger critique** are written by the embedded **`N/llm`** model (OCI Generative AI),
and the result is emailed to a reviewer as a DRAFT and saved to the File Cabinet. No external
orchestrator, no data leaving the platform.

This is the in-platform sibling of the external Python build ([../](..)). It keeps the same right-size
rule — **code flags, AI only judges the grey areas, code has the last word** — and the same
maker-checker seam: a second agent challenges the first, and a deterministic guard rejects any figure
the model invents. See the [repo README](../../README.md#build-2--manual-je-anomaly-reviewer-detective-control--maker-checker)
for the build-vs-buy case.

> **Status: builds + unit-tests green off-platform (19 Jest tests).** The SuiteQL register wiring
> (preparer/approver/support fields) has account-specific assumptions called out under *Known limits*;
> validate those on your account before the first live run, exactly as the flux build's DEPLOY.md
> walks through.

## What's here

```
suitescript-je-review/
  src/                                  SDF account-customization project
    manifest.xml  deploy.xml
    Objects/customscript_je_review.xml          Scheduled Script + deployment record
    FileCabinet/SuiteScripts/je_review/
      je_config.js       config defaults (or override via Script Parameters)
      je_sql.js          SuiteQL builders (periods + closed flag, journal headers, journal lines)
      je_rules.js        THE RULE ENGINE — 10 pure rules + risk score/tier (ported from je_rules.py)
      je_guard.js        THE AUDIT SEAM — number-trace guard over the AI note
      je_review_ai.js    N/llm reviewer + challenger (the maker-checker AI step)
      je_report.js       deterministic HTML reviewer worklist
      je_scheduled.js    orchestrator (entry point)
  __tests__/             Jest unit tests for je_rules + je_guard (off-platform)
  package.json  jest.config.js  suitecloud.config.js
```

The flow mirrors the Python pipeline: **periods (+ closed flag) → manual-journal headers + lines →
assemble register → `assessRegister` (rules + score) → per flagged entry: `N/llm` reviewer →
`guardNote` → `N/llm` challenger → HTML worklist → email reviewer + save file.**

## The right-size split (identical to the Python build)

| Step | Owner |
|------|-------|
| Pull the manual-JE register | SuiteQL (`je_sql.js`) |
| Flag anomalies + risk score + tier | **Code** (`je_rules.js`, 10 pure rules) |
| Decide who must review (disposition) | **Code** — high / score ≥ 5 auto-escalates |
| Judge grey-zone cases + write the note | **AI — reviewer** (`N/llm`, cheaper family) |
| Challenge it (false positive / missed risk) | **AI — challenger** (`N/llm`, larger family) |
| Verify every figure in the note traces to source | **Code** (`je_guard.js`) |
| Assemble the worklist | **Code** (`je_report.js`) |

## Prerequisites

1. **SuiteScript Generative AI (`N/llm`) enabled** — it is region-gated; confirm your data center is
   supported. The free monthly call quota covers a normal month of flagged journals (only high/medium
   entries hit the model; low/clear are accepted in code). Beyond it, configure your own OCI
   Generative AI credentials (Setup → Company → AI preferences).
2. **Features on:** *SuiteCloud → SuiteScript → Server SuiteScript*.
3. **A role with** SuiteScript deploy + SuiteQL (Analytics) + send-email permissions.
4. For the CLI path: **Token-Based Authentication** + the SuiteCloud CLI (`@oracle/suitecloud-cli`)
   and Node 18+.
5. **Test in a Sandbox / Release Preview first** — it emails and writes files.

## Configure

Edit defaults in [`src/FileCabinet/SuiteScripts/je_review/je_config.js`](src/FileCabinet/SuiteScripts/je_review/je_config.js)
(thresholds, accounting book, reviewer email, report folder id, model families, and the
approver/support field ids). Every value can also be overridden at deploy time with a **Script
Parameter** of the matching id (`custscript_je_threshold`, `custscript_je_book`, `custscript_je_months`,
`custscript_je_reviewer`, `custscript_je_folder`, `custscript_je_model`, `custscript_je_model_chal`,
`custscript_je_approver_field`, `custscript_je_support_field`, `custscript_je_approver_rules`) — the
script reads the parameter and falls back to the config default.

> A click-by-click walkthrough (feature toggles, an `N/llm` pre-flight check, both deploy paths,
> testing, troubleshooting) is in [DEPLOY.md](DEPLOY.md).

## Deploy — SuiteCloud CLI

```bash
npm install                      # CLI + unit-testing framework
npx suitecloud account:setup     # authenticate (TBA) to your sandbox
npm test                         # off-platform unit tests (rules + guard)
npx suitecloud project:validate --server
npx suitecloud project:deploy
```

`project:deploy` uploads the scripts to `/SuiteScripts/je_review/` and creates the **Scheduled Script**
+ deployment (`customscript_je_review` / `customdeploy_je_review`), landing as **Not Scheduled**. Open
the deployment → set a monthly schedule (e.g. the 3rd at 06:00), or **Save & Execute** for a test run.

## Verify a run

- **Email:** the reviewer receives *"Manual JE anomaly review … — N to escalate"* with the worklist.
- **File Cabinet:** an HTML copy `je_review_<period>.html` is saved (the reliable sandbox artifact).
- **Execution Log** (on the deployment): an `AUDIT` summary — journals assessed, # escalate, four-eyes
  overrides, and notes withheld. A note whose figures don't trace to source is **withheld** (shown
  with a red warning), never relied upon.

## Tests

`npm test` runs the Jest suites against `je_rules` and `je_guard` off-platform (the SuiteCloud unit-
testing framework transforms the AMD modules and stubs `N/*`). These are the same assertions as the
Python `test_je_*` suites — every rule's fire/no-fire cases, the tier scoring, the **10 planted
anomalies all caught with 0 false positives**, and the audit seam (invented figure rejected, account
code/JE id allowed, ordinals not policed).

## Known limits & honest caveats

- **Preparer / approver / support are account-specific.** Out of the box NetSuite has no single
  "who approved" column, so `APPROVER_FIELD` defaults to the routed next-approver; point it at your
  approval custom field if you capture the actual approver. `HAS_SUPPORT_FIELD` is blank by default
  (so `no_support` won't flag everything) — wire it to your attachment-tracking checkbox to enable the
  rule live. The off-platform tests exercise every rule regardless of this wiring.
- **No JE approval workflow? Turn the approver rule off.** If your account doesn't approve journals
  in-platform, the `sod_breach` "no independent approver" branch has no signal and would flag every
  entry. Set `ENABLE_APPROVER_RULES: false` (or the `custscript_je_approver_rules` parameter) to skip
  it — the rest of the control (thresholds, round-dollar, off-hours, near-duplicate, closed-period,
  sensitive-account) is unaffected. *Verified live against a NetSuite sandbox: with the rule off, an Apr
  2026 run of 16 CIT accruals returned a clean 7 monitor / 9 logged, 0 escalate, 0 guard failures —
  only genuine `over_threshold` and `near_duplicate` signals remained.*
- **Posting timestamp.** `off_hours` uses `transaction.createddate` (when the journal was entered) as
  the posting time — the closest native signal to "when was this posted".
- **Representative account.** A journal has many lines; the register shows one representative account
  per journal — a **sensitive** (control/bank/equity) line wins, else the largest line — so
  `sensitive_account` surfaces a control-account touch even in a multi-line entry.
- **Closed periods** come from the native `accountingperiod.closed` / `alllocked` flags — no
  hard-coded list.
- **Model quality.** `N/llm` runs OCI models (default Cohere Command R) — capable, but below frontier
  Claude for nuance. The prompts are tight and structured, and if the model won't return clean JSON
  the reviewer degrades to a tier-derived call and the challenger to the deterministic four-eyes check
  — so the control never depends on the model formatting correctly.
- **Governance.** One reviewer + one challenger `generateText` per *flagged* entry keeps a normal
  month within the Scheduled Script unit limits and the `N/llm` quota; for very large registers add
  `N/runtime` yield/reschedule (not included).
- **"Draft, never send"** is emulated by emailing a **reviewer** + saving a file (NetSuite has no
  Gmail-style draft). The human acts after approving.

## Why this still keeps the build's edge

The one thing the native `N/llm` route doesn't give you is a deterministic *"the AI never invented a
figure"* check and an explicit *second agent that challenges the first*. `je_guard.js` and the
challenger in `je_review_ai.js` are exactly that — ported intact — so even on the in-platform,
weaker-model path, an invented figure cannot reach the worklist and a high-severity flag cannot be
waved through. That seam is the reason to build it this way rather than just calling `generateText`
and trusting the output.
