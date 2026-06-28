# SuiteScript flux review (embedded `N/llm`) — Option 4, built

A NetSuite-native version of the flux automation: the deterministic calc (variance gate, grounded
drivers, vendor bridge, trend) and the **number/provenance audit seam** run as SuiteScript inside
NetSuite, the narrative is written by the embedded **`N/llm`** model (OCI Generative AI), and the
result is emailed to a reviewer as a DRAFT and saved to the File Cabinet. No external orchestrator, no
data leaving the platform.

This is the in-platform sibling of the external Python build (`Week1/`). It deliberately keeps the
same right-size rule — **the model only writes prose; every figure is computed and verified in code.**
See [../flux_approaches_comparison.md](../flux_approaches_comparison.md) for the trade-offs (model
quality, data residency, who builds the eval).

## What's here

```
suitescript-flux/
  src/                                  SDF account-customization project
    manifest.xml  deploy.xml
    Objects/customscript_flux_review.xml        Scheduled Script + deployment record
    FileCabinet/SuiteScripts/flux/
      flux_config.js       config defaults (or override via Script Parameters)
      flux_sql.js          SuiteQL builders (periods, flux, grounded drivers, history)
      flux_calc.js         tolerance gate, variance, vendor_bridge, trend, sensitivity, confidence
      flux_eval.js         THE AUDIT SEAM — number-match + provenance + reference whitelisting
      flux_narrative.js    N/llm generateText wrapper + the prompt (the only AI step)
      flux_report.js       deterministic HTML report
      flux_scheduled.js    orchestrator (entry point)
  __tests__/               Jest unit tests for flux_calc + flux_eval (off-platform)
  package.json  jest.config.js  suitecloud.config.js
```

The flow mirrors the Python pipeline: **periods → flux SuiteQL → `flagReviews` → grounded drivers +
history → `vendorBridge`/`trendFacts`/`confidence`/`sensitivity` → `N/llm` narrative → `checkExplanation`
→ HTML report → email reviewer + save file.**

## Prerequisites (check these first)

1. **SuiteScript Generative AI (`N/llm`) is available and enabled.** It is **region-gated** — confirm
   your account's data center is supported, then enable server-side scripting. The free monthly call
   quota covers a handful of flagged accounts per run; beyond it, configure your own OCI Generative AI
   credentials (Setup → Company → AI preferences) for metered usage.
2. **Features on:** *SuiteCloud → SuiteScript → Server SuiteScript* (and Client if you extend it).
3. **A role with** SuiteScript deploy + SuiteQL (Analytics) + send-email permissions.
4. For the CLI path: **Token-Based Authentication** + the SuiteCloud CLI (`@oracle/suitecloud-cli`)
   and Node 18+.
5. **Test in a Sandbox / Release Preview first** — it emails and writes files.

## Configure

Edit defaults in [`src/FileCabinet/SuiteScripts/flux/flux_config.js`](src/FileCabinet/SuiteScripts/flux/flux_config.js)
(thresholds, accounting book, reviewer email, report folder id, model family). Every value can also be
overridden at deploy time with a **Script Parameter** of the matching id (`custscript_flux_abs`,
`custscript_flux_pct`, `custscript_flux_book`, `custscript_flux_history`, `custscript_flux_reviewer`,
`custscript_flux_folder`, `custscript_flux_model`) — the script reads the parameter and falls back to
the config default, so it runs either way.

> **Want the click-by-click version?** A detailed walkthrough — feature toggles, an `N/llm` pre-flight
> check, both deploy paths, a full testing section, and a troubleshooting table — is in
> [DEPLOY.md](DEPLOY.md). The summary below is the quick path.

## Deploy — Option A: SuiteCloud CLI (recommended)

From `Week1/suitescript-flux/`:

```bash
npm install                      # CLI + unit-testing framework
npx suitecloud account:setup     # authenticate (TBA) to your sandbox
npm test                         # run the off-platform unit tests (calc + eval)
npx suitecloud project:validate --server
npx suitecloud project:deploy
```

`project:deploy` uploads the scripts to `/SuiteScripts/flux/` and creates the **Scheduled Script** +
deployment (`customscript_flux_review` / `customdeploy_flux_review`). The deployment lands as
**Not Scheduled** so nothing fires until you set a schedule (next step).

## Deploy — Option B: manual UI (no CLI)

1. **File Cabinet** → upload the six `flux_*.js` files into a folder, e.g. `SuiteScripts/flux/`
   (keep them together — they load each other by relative path).
2. **Customization → Scripting → Scripts → New** → select `flux_scheduled.js` → type **Scheduled
   Script** → name it → **Save**.
3. On the script record, **Deploy Script**: set status, log level **Audit**, and (optionally) add the
   Script Parameters listed above.
4. Save.

## Schedule it

Open the deployment → set **Status = Scheduled** and a monthly recurrence (e.g. the 5th at 06:00, to
match the Python routine). Save. Use **Save & Execute** (or *Scheduled Script Status*) for an immediate
test run.

## Verify a run

- **Email:** the reviewer (`REVIEWER_EMAIL`) receives *"Flux review (SuiteScript + N/llm) — … (DRAFT
  for review)"* with the table + per-account explanations.
- **File Cabinet:** if `REPORT_FOLDER_ID` is set, an HTML copy `flux_<period>.html` is saved.
- **Execution Log** (on the deployment): an `AUDIT` summary line — periods used, # REVIEW, # verified,
  # within tolerance — plus a `withheld` line for any narrative that failed the eval.

A narrative whose figures don't trace to source is **withheld** (shown as a red "failed verification"
flag), never shipped — exactly as in the Python build.

## Tests

`npm test` runs the Jest suites against `flux_calc` and `flux_eval` off-platform (the SuiteCloud unit-
testing framework transforms the AMD modules and stubs `N/*`). These are the same assertions as the
Python `test_ns_flux_*` suites — the gate, vendor bridge, trend, and the audit seam (invented number
rejected, invented vendor rejected, cited refs/memos allowed).

## Known limits & honest caveats

- **Model quality.** `N/llm` runs OCI models (default Cohere Command R) — capable, but generally below
  frontier Claude for nuanced finance prose. The prompt is kept tight and structured to compensate.
- **Region & quota.** Feature availability is regional; the free call quota is finite (BYO-OCI beyond
  it). With many flagged accounts you may approach the monthly quota or the 5-concurrent-call limit.
- **Governance.** A Scheduled Script has unit limits; one `generateText` per flagged account is fine
  for a normal month. For very large result sets, add `N/runtime` yield/reschedule (not included).
- **YTD column** is shown as `n/a` here — the Python build reads YTD straight from the saved search;
  this build computes periodic + SPLY + trend. Add a fiscal-year `period_total` query to populate it.
- **Periods** are resolved by calendar month-end (`LAST_DAY(ADD_MONTHS(SYSDATE,-1))`); adjust
  `recentPeriodsSql` if your accounting periods aren't standard monthly.
- **"Draft, never send"** is emulated by emailing a **reviewer** (not finance) + saving a file, since
  NetSuite has no Gmail-style draft. The human forwards after approving.

## Why this still keeps the build's edge

The one thing the native `N/llm` route doesn't give you out of the box is a deterministic
*"the AI never changed a number"* check. `flux_eval.js` is that check, ported intact — so even on the
in-platform, weaker-model path, an invented figure or vendor cannot reach the report. That seam is the
reason to build it this way rather than just calling `generateText` and trusting the output.
