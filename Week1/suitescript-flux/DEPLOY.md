# Deploy & test — detailed walkthrough

A click-by-click guide to getting the SuiteScript flux review running in NetSuite and testing it
safely. If you just want the short version, see [README.md](README.md). **Do everything in a Sandbox
or Release Preview account first** — this script sends email and writes files.

Menu paths below are the standard NetSuite ones; your account's wording may differ slightly by version
or role. You need an **Administrator** (or equivalent customization) role.

---

## 0. What you'll end up with

- 6 script files in **File Cabinet → `SuiteScripts/flux/`**
- one **Scheduled Script** record (`customscript_flux_review`) + a **deployment** (`customdeploy_flux_review`)
- a monthly schedule that emails a reviewer a DRAFT flux report and saves an HTML copy

Two ways to get there: **Path A (SuiteCloud CLI)** — repeatable, version-controlled, recommended; or
**Path B (manual UI)** — no tooling, all in the browser. Do the **pre-flight (Section 3)** either way.

---

## 1. Prerequisites

### 1.1 Account & role
- Administrator role (or a role with: Lists/Records, **SuiteScript**, **SuiteAnalytics/Workbook**
  (for SuiteQL), **Publish Dashboards/Documents** (File Cabinet), and **Send Email**).
- A **Sandbox** (Setup → Company → Sandbox Accounts) or **Release Preview** to test in.

### 1.2 Turn on the features
**Setup → Company → Enable Features → SuiteCloud** tab:
- **SuiteScript**: tick **Server SuiteScript** (and **Client SuiteScript**). Accept the terms.
- For Path A also tick: **SuiteCloud Development Framework**, **Token-Based Authentication**, and
  **Manage Authentication Tokens**.
- Save.

### 1.3 Confirm the embedded AI (`N/llm`) is available
The SuiteScript Generative AI APIs are **region-gated** (tied to your account's data center) and use a
**monthly free call quota**. There isn't always a separate on/off switch beyond Server SuiteScript, so
the reliable check is the **pre-flight script in Section 3** — if `llm.generateText` returns text,
you're good. If it errors with "feature not available in your account/region," you'll need to either be
in a supported region or configure your own OCI Generative AI credentials
(**Setup → Company → General Preferences / AI** area) — note this and stop here if it's unavailable.

---

## 2. Get the code

Clone the repo (or copy the `Week1/suitescript-flux/` folder) to your machine:

```bash
git clone https://github.com/darbit1/finance-automation-lab
cd finance-automation-lab/Week1/suitescript-flux
```

---

## 3. Pre-flight — confirm `N/llm` works (2 minutes, do this first)

Before deploying anything, prove the embedded model is callable in your account. In the UI:

1. **Customization → Scripting → Scripts → New.**
2. Upload a tiny throwaway file (File Cabinet → upload first, or create it):

```javascript
/**
 * @NApiVersion 2.1
 * @NScriptType ScheduledScript
 */
define(['N/llm', 'N/log'], function (llm, log) {
  return {
    execute: function () {
      var r = llm.generateText({
        prompt: 'Reply with the single word: OK',
        modelFamily: llm.ModelFamily.COHERE_COMMAND_R,
        modelParameters: { maxTokens: 10, temperature: 0 }
      });
      log.audit('LLM pre-flight', r.text);
    }
  };
});
```

3. Create it as a **Scheduled Script**, add a deployment, then **Save & Execute**.
4. **Customization → Scripting → Script Execution Logs** (or *Scheduled Script Status*) → you should
   see an `AUDIT` line with the model's reply. ✅ means the feature, region, and quota all work.
   If it errors, fix that before continuing (see Troubleshooting).

Delete the throwaway script afterwards.

---

## 4. Configure

Open [`src/FileCabinet/SuiteScripts/flux/flux_config.js`](src/FileCabinet/SuiteScripts/flux/flux_config.js)
and set:

| Field | What to set |
|---|---|
| `ABS_THRESHOLD` / `PCT_THRESHOLD` | materiality gate (default 25000 / 0.10) |
| `ACCOUNTING_BOOK` | the book to report on (1 = Primary) |
| `HISTORY_MONTHS` | trailing months for trend/SPLY (default 12) |
| `REVIEWER_EMAIL` | **who receives the draft** — set this to a real inbox you control for testing |
| `REPORT_FOLDER_ID` | File Cabinet folder **internal id** to save the HTML into (-1 = skip) |
| `MODEL_FAMILY` | `COHERE_COMMAND_R` (default), `COHERE_COMMAND_R_PLUS`, or `META_LLAMA` |

To find a folder's internal id: **Documents → Files → File Cabinet**, open the folder, read `folder=`
in the URL (or enable internal ids under Home → Set Preferences → show internal ids).

> Tip for the first test: set `ABS_THRESHOLD` low (e.g. `1000`) so plenty of accounts flag and you get
> a full report to inspect, then restore it to `25000`.

You can instead leave the file as-is and set **Script Parameters** at deploy time (Section 5.B.4 / 6) —
the script reads the parameter and falls back to the config default.

---

## 5. Deploy

### Path A — SuiteCloud CLI (recommended)

From `Week1/suitescript-flux/`:

```bash
npm install
```
Installs the SuiteCloud CLI and the unit-testing framework (Node 18+).

```bash
npx suitecloud account:setup
```
Choose **browser-based authentication**, log into your **sandbox**, authorize, and give the
authentication ID a name (e.g. `flux-sb`). This stores the token locally — no manual integration record
needed.

```bash
npm test
```
Runs the off-platform Jest tests for `flux_calc` + `flux_eval`. All should pass before you deploy.

```bash
npx suitecloud project:validate --server
```
Server-side validation of the SDF project (catches manifest/object problems before deploy).

```bash
npx suitecloud project:deploy
```
Uploads the six scripts to `/SuiteScripts/flux/` and creates the Scheduled Script + deployment. On
success you'll see the objects listed as deployed. The deployment lands as **Not Scheduled** (Section 6).

> If `project:deploy` complains about the `SERVERSIDESCRIPTING` feature, confirm Section 1.2. If it
> complains about an object already existing, you've already deployed — use `--accountspecificvalues
> WARNING` or update instead.

### Path B — manual UI (no CLI)

**5.B.1 Upload the scripts.** Documents → Files → **File Cabinet** → into `SuiteScripts/` create a
folder `flux` → **Add File** (or **Advanced Add** to multi-upload) → add all six:
`flux_config.js, flux_sql.js, flux_calc.js, flux_eval.js, flux_narrative.js, flux_report.js`,
**and** `flux_scheduled.js`. Keep them in the **same folder** (they load each other by relative path).

**5.B.2 Create the script record.** Customization → Scripting → **Scripts → New** → in the popup select
the file **`flux_scheduled.js`** → **Create Script Record**. NetSuite reads the JSDoc and sets type
**Scheduled Script**. Name it `Flux Review (SuiteScript + N/llm)`, ID `customscript_flux_review`. **Save.**

**5.B.3 Deploy it.** On the script record → **Deployments** subtab → **New Deployment** (or the
*Deploy Script* button) → Title `Flux Review - Monthly`, **Status = Testing** (for now), **Log Level =
Audit**, leave **Schedule** empty. **Save.**

**5.B.4 (Optional) Script Parameters.** On the script record → **Parameters** subtab → add fields with
ids `custscript_flux_abs`, `custscript_flux_pct`, `custscript_flux_book`, `custscript_flux_history`,
`custscript_flux_reviewer`, `custscript_flux_folder`, `custscript_flux_model` (types: float / float /
integer / integer / free-text / integer / free-text). Set their values on the **deployment**. Skip this
if you configured `flux_config.js` directly.

---

## 6. Schedule it

Open the deployment (Customization → Scripting → **Script Deployments**, filter to the flux script):
- For production: **Status = Scheduled**, then set the **Schedule** subtab — e.g. **Monthly**, day **5**,
  start **06:00**, to match the Python routine.
- **Save.**

(Leave it **Testing** while you iterate in Section 7 — Testing status lets only you run it.)

---

## 7. Testing

### 7.1 First run — execute on demand
On the deployment record click **Save & Execute** (or set Status = Testing, then
**Customization → Scripting → Scheduled Script Status → Submit New Instance**).

### 7.2 Read the execution log
Customization → Scripting → **Script Execution Logs** (filter to your script). Expect:
- an `AUDIT` **summary** line: `<current> vs <prior> | REVIEW=N | verified=N | within tolerance=N`
- any `AUDIT` **withheld** lines (a narrative the eval rejected — by design)
- no `ERROR` lines. If you see one, jump to Troubleshooting.

### 7.3 Check the outputs
- **Email:** the `REVIEWER_EMAIL` inbox gets *"Flux review (SuiteScript + N/llm) — … (DRAFT for
  review)"* — confirm the table renders and each flagged account has a narrative (or a red
  "withheld" flag).
- **File Cabinet:** if `REPORT_FOLDER_ID` is set, `flux_<period>.html` appears in that folder.

### 7.4 Force flags so there's something to see
If "REVIEW=0", lower `ABS_THRESHOLD` (e.g. to 1000) and re-run — most months will then flag several
accounts. Restore it afterwards.

### 7.5 (Optional) Sanity-check the SuiteQL independently
To see the raw numbers the script works from, run the same SuiteQL outside the script — e.g. via the
free community **"SuiteQL Query Tool"** SuiteApp, or **Analytics → New Workbook** (SuiteQL). Paste the
string `flux_sql.fluxSql(currId, priorId, 1)` would build (you can log it from the script, or copy from
the repo) and confirm the current/prior periodic columns match your trial balance.

### 7.6 (Optional) Prove the audit seam withholds
The off-platform tests already prove it, but to see it live: temporarily edit the prompt in
`flux_narrative.js` to instruct the model to "add an unrelated figure of EUR 999,999," redeploy, run,
and confirm that account shows the **red "withheld — failed verification"** block instead of shipping
the bad number. Revert the edit afterwards.

### 7.7 Watch the AI budget
Each flagged account = one `generateText` call. A normal month is a handful; if you forced a low
threshold you may make dozens — fine for a test, but mind the **monthly free quota** and the
**5-concurrent-call** limit.

---

## 8. Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| `MODULE_DOES_NOT_EXIST: N/llm` or "feature not available" | Generative AI not available in your region/account → confirm region; configure OCI credentials, or this approach isn't available to you. |
| Pre-flight returns nothing / quota error | Monthly free quota exhausted, or concurrency limit → wait for reset or add OCI credentials. |
| `SSS_MISSING_REQD_ARGUMENT` / SuiteQL error | A column/table name differs in your account → run the SuiteQL standalone (7.5) and adjust `flux_sql.js`. |
| `INSUFFICIENT_PERMISSION` on email/file | Role lacks Send Email or File Cabinet → add the permission, or change `REVIEWER_EMAIL`/`REPORT_FOLDER_ID`. |
| Email `author` error | `runtime.getCurrentUser().id` isn't a valid employee in this context → set the deployment owner to a real employee, or hard-code an author id in `sendAndSave`. |
| `SSS_TIME_LIMIT_EXCEEDED` / governance | Too many flagged accounts in one run → raise the threshold, or add `N/runtime` yield/reschedule (noted in README limits). |
| REVIEW=0 every run | Nothing exceeded tolerance → lower `ABS_THRESHOLD` to test (7.4). |
| Periods resolve wrong | Non-standard accounting periods → adjust `recentPeriodsSql` in `flux_sql.js`. |
| Modules "not found" at runtime (manual deploy) | The six files aren't in the **same** File Cabinet folder → move them together. |

Turn **Log Level = Debug** on the deployment for more detail while diagnosing, then back to Audit.

---

## 9. Promote to production

Once it's clean in sandbox:
- **CLI:** `suitecloud account:setup` a second auth id for production, then `project:deploy` against it.
- **Manual:** re-upload the files + recreate the script/deployment in production (or use SDF/Bundle).
- Set the deployment **Status = Scheduled** with the monthly schedule, **Log Level = Audit**, and point
  `REVIEWER_EMAIL` at the real reviewer. Keep it a **draft to a reviewer** — never auto-send to finance.

## 10. Disable / roll back
- Pause: open the deployment → **Status = Not Scheduled** (or Undeployed) → Save.
- Remove: delete the deployment, the script record, then the files (or `suitecloud object:delete`).
