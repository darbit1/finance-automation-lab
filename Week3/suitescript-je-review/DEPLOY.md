# Deploy & test — detailed walkthrough

A click-by-click guide to getting the SuiteScript manual-JE anomaly reviewer running in NetSuite and
testing it safely. For the short version, see [README.md](README.md). **Do everything in a Sandbox or
Release Preview account first** — this script sends email and writes files.

Menu paths are the standard NetSuite ones; your account's wording may differ by version or role. You
need an **Administrator** (or equivalent customization) role.

---

## 0. What you'll end up with

- 7 script files in **File Cabinet → `SuiteScripts/je_review/`**
- one **Scheduled Script** record (`customscript_je_review`) + a **deployment** (`customdeploy_je_review`)
- a monthly schedule that emails a reviewer a DRAFT anomaly worklist and saves an HTML copy

Two ways there: **Path A (SuiteCloud CLI)** — repeatable, version-controlled, recommended; or **Path B
(manual UI)** — all in the browser. Do the **pre-flight (Section 3)** either way.

---

## 1. Prerequisites

### 1.1 Account & role
- Administrator role (or a role with: Lists/Records, **SuiteScript**, **SuiteAnalytics/Workbook** for
  SuiteQL, **Publish Dashboards/Documents** for File Cabinet, and **Send Email**).
- A **Sandbox** (Setup → Company → Sandbox Accounts) or **Release Preview** to test in.

### 1.2 Turn on the features
**Setup → Company → Enable Features → SuiteCloud** tab:
- **SuiteScript**: tick **Server SuiteScript**. Accept the terms.
- For Path A also tick: **SuiteCloud Development Framework**, **Token-Based Authentication**, and
  **Manage Authentication Tokens**.
- Save.

### 1.3 Confirm the embedded AI (`N/llm`) is available
The SuiteScript Generative AI APIs are **region-gated** and use a **monthly free call quota**. The
reliable check is the **pre-flight in Section 3** — if `llm.generateText` returns text, you're good.
If it errors with "feature not available in your account/region," you'll need a supported region or
your own OCI Generative AI credentials (**Setup → Company → General Preferences / AI**) — note this and
stop here if unavailable.

---

## 2. Get the code

```bash
git clone https://github.com/darbit1/finance-automation-lab
cd finance-automation-lab/Week3/suitescript-je-review
```

---

## 3. Pre-flight — confirm `N/llm` works (2 minutes, do this first)

Prove the embedded model is callable before deploying anything:

1. **Customization → Scripting → Scripts → New.**
2. Upload a tiny throwaway file:

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
4. **Customization → Scripting → Script Execution Logs** → you should see an `AUDIT` line with the
   model's reply. ✅ means feature, region, and quota all work. Delete the throwaway afterwards.

> The reviewer prompt asks for `COHERE_COMMAND_R` and the challenger for `COHERE_COMMAND_R_PLUS`. If
> the `_PLUS` family isn't enabled in your account, set `CHALLENGER_MODEL` to `COHERE_COMMAND_R` in
> `je_config.js` — the deterministic four-eyes fallback still enforces the control either way.

---

## 4. Configure

Open [`src/FileCabinet/SuiteScripts/je_review/je_config.js`](src/FileCabinet/SuiteScripts/je_review/je_config.js)
and set:

| Field | What to set |
|---|---|
| `APPROVAL_THRESHOLD` / `ROUND_MIN` | materiality thresholds (default 50000 / 10000) |
| `ACCOUNTING_BOOK` | the book to review (1 = Primary) |
| `REVIEW_MONTHS` | how many recent periods to sweep (default 1 = the open month) |
| `REVIEWER_EMAIL` | **who receives the draft** — a real inbox you control for testing |
| `REPORT_FOLDER_ID` | File Cabinet folder **internal id** to save the HTML into (-1 = resolve by name `je_review`) |
| `APPROVER_FIELD` | column supplying the approver (default `nextapprover`; point at your approval custom field if you capture the actual approver) |
| `HAS_SUPPORT_FIELD` | checkbox body field recording whether support is attached — **leave blank to disable `no_support` live**, or wire it to your convention |
| `ENABLE_APPROVER_RULES` | `true` (default) where journals are approved in-platform; **set `false` if your account has no JE approval workflow** (else `sod_breach` flags every entry) |
| `REVIEWER_MODEL` / `CHALLENGER_MODEL` | `N/llm` families (defaults `COHERE_COMMAND_R` / `COHERE_COMMAND_R_PLUS`) |

To find a folder's internal id: **Documents → Files → File Cabinet**, open the folder, read `folder=`
in the URL. You can instead leave the file as-is and set **Script Parameters** at deploy time
(Section 5.B.4) — the script reads the parameter and falls back to the config default.

> **Field-wiring note (important).** `preparer` comes from `createdby`, `post_ts` from `createddate`.
> `approver` and `has_support` are account-specific (see README *Known limits*). The **rule engine is
> proven off-platform** by `npm test` regardless; wiring these fields is what makes the `sod_breach`
> and `no_support` rules fire on *your* live data.

---

## 5. Deploy

### Path A — SuiteCloud CLI (recommended)

From `Week3/suitescript-je-review/`:

```bash
npm install                      # SuiteCloud CLI + unit-testing framework (Node 18+)
npx suitecloud account:setup     # browser auth into your SANDBOX; name the auth id e.g. je-sb
npm test                         # off-platform Jest tests (rules + guard) — all should pass
npx suitecloud project:validate --server
npx suitecloud project:deploy
```

`project:deploy` uploads the seven scripts to `/SuiteScripts/je_review/` and creates the Scheduled
Script + deployment. It lands as **Not Scheduled** (Section 6).

> If `npm install` hangs on the CLI's SDK download (a JAR fetch), you can still run the tests with just
> `npm install --no-save jest @oracle/suitecloud-unit-testing` — the CLI is only needed for
> validate/deploy, not for `npm test`.

### Path B — manual UI (no CLI)

**5.B.1 Upload the scripts.** Documents → Files → **File Cabinet** → under `SuiteScripts/` create a
folder `je_review` → **Advanced Add** → add all seven: `je_config.js, je_sql.js, je_rules.js,
je_guard.js, je_review_ai.js, je_report.js`, **and** `je_scheduled.js`. Keep them in the **same
folder** (they load each other by relative path).

**5.B.2 Create the script record.** Customization → Scripting → **Scripts → New** → select
**`je_scheduled.js`** → **Create Script Record**. NetSuite reads the JSDoc and sets type **Scheduled
Script**. Name it `Manual JE Anomaly Review (SuiteScript + N/llm)`, ID `customscript_je_review`. **Save.**

**5.B.3 Deploy it.** On the script record → **Deployments** → **New Deployment** → Title
`Manual JE Anomaly Review - Monthly`, **Status = Testing**, **Log Level = Audit**, leave **Schedule**
empty. **Save.**

**5.B.4 (Optional) Script Parameters.** On the script record → **Parameters** → add fields with ids
`custscript_je_threshold`, `custscript_je_book`, `custscript_je_months`, `custscript_je_reviewer`,
`custscript_je_folder`, `custscript_je_model`, `custscript_je_model_chal`,
`custscript_je_approver_field`, `custscript_je_support_field`, `custscript_je_approver_rules` (types:
float / integer / integer / free-text / integer / free-text / free-text / free-text / free-text /
checkbox). Set values on the **deployment**. Skip if you configured `je_config.js` directly.

---

## 6. Schedule it

Open the deployment (Customization → Scripting → **Script Deployments**, filter to the JE script):
- Production: **Status = Scheduled**, then **Schedule** subtab — e.g. **Monthly**, day **3**, start
  **06:00** (early, so a controller has the worklist at the start of the close).
- **Save.** (Leave it **Testing** while you iterate in Section 7.)

---

## 7. Testing

### 7.1 First run
On the deployment click **Save & Execute** (or Status = Testing → **Scheduled Script Status → Submit
New Instance**).

### 7.2 Read the execution log
Customization → Scripting → **Script Execution Logs**. Expect:
- an `AUDIT` **summary** line: `<periods> | journals=N | escalate=N | four-eyes overrides=N | notes withheld=N`
- any `AUDIT` **note withheld** lines (a reviewer note the guard rejected — by design)
- no `ERROR` lines. If you see one, jump to Troubleshooting.

### 7.3 Check the outputs
- **Email:** the `REVIEWER_EMAIL` inbox gets *"Manual JE anomaly review … — N to escalate"* — confirm
  the worklist renders, each flagged entry shows its flags, reviewer note, and challenger verdict.
- **File Cabinet:** `je_review_<period>.html` appears in the resolved folder (the reliable sandbox
  artifact — sandboxes often suppress outbound email).

### 7.4 No manual journals in the period?
If `journals=0`, either widen the window (`REVIEW_MONTHS`) or post a couple of synthetic manual
journals in the sandbox (Transactions → Financial → **Make Journal Entries**) — include a large,
unsupported one to a control account to see an escalation.

### 7.5 (Optional) Prove the audit seam withholds
The off-platform tests prove it, but to see it live: temporarily edit the reviewer prompt in
`je_review_ai.js` to instruct the model to "mention a fabricated exposure of 999,999", redeploy, run,
and confirm that entry shows the **⚠️ note failed the audit seam** warning instead of relying on the
bad figure. Revert afterwards.

### 7.6 (Optional) Prove the challenger overrides
Post a manual JE to a control account and set `REVIEWER_MODEL` to a family prone to under-calling; the
**code guard-rail forces `escalate` on any high-severity flag**, and a `missed_risk` challenge is
reflected in the summary's *four-eyes overrides* count.

### 7.7 Watch the AI budget
Each **flagged** (high/medium) entry = one reviewer + one challenger `generateText` call; low/clear
entries make **no** calls. A normal month is a handful — mind the monthly free quota and the
5-concurrent-call limit if you post many test journals.

---

## 8. Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| `MODULE_DOES_NOT_EXIST: N/llm` or "feature not available" | Generative AI not available in your region/account → confirm region; configure OCI credentials, or this approach isn't available to you. |
| Challenger errors on `COHERE_COMMAND_R_PLUS` | That family isn't enabled → set `CHALLENGER_MODEL = 'COHERE_COMMAND_R'`; the deterministic four-eyes fallback still runs. |
| Pre-flight returns nothing / quota error | Monthly free quota exhausted, or concurrency limit → wait for reset or add OCI credentials. |
| SuiteQL error on `nextapprover` / a support column | That column doesn't exist in your account → set `APPROVER_FIELD` to a valid one and leave `HAS_SUPPORT_FIELD` blank. |
| `sod_breach` fires on everything | No approver captured on journals → expected ("no independent approver", medium); wire `APPROVER_FIELD` to your real approver field to quiet it. |
| `no_support` never fires | `HAS_SUPPORT_FIELD` blank → defaults to "supported"; wire it to your attachment checkbox. |
| `INSUFFICIENT_PERMISSION` on email/file | Role lacks Send Email or File Cabinet → add the permission, or change `REVIEWER_EMAIL`/`REPORT_FOLDER_ID`. |
| Email `author` error | Author isn't a valid employee with an email → set `AUTHOR_EMPLOYEE_ID` to a real employee id (see README). |
| `SSS_TIME_LIMIT_EXCEEDED` / governance | Too many flagged journals in one run → narrow `REVIEW_MONTHS`, or add `N/runtime` yield/reschedule (noted in README limits). |
| Periods resolve wrong | Non-standard accounting periods → adjust `recentPeriodsSql` in `je_sql.js`. |
| Modules "not found" at runtime (manual deploy) | The seven files aren't in the **same** File Cabinet folder → move them together. |

Turn **Log Level = Debug** on the deployment for more detail while diagnosing, then back to Audit.

---

## 9. Promote to production

Once clean in sandbox:
- **CLI:** `suitecloud account:setup` a second auth id for production, then `project:deploy` against it.
- **Manual:** re-upload the files + recreate the script/deployment (or use SDF/Bundle).
- Set **Status = Scheduled** with the monthly schedule, **Log Level = Audit**, point `REVIEWER_EMAIL`
  at the real reviewer, and wire `APPROVER_FIELD` / `HAS_SUPPORT_FIELD` to your account's fields. Keep
  it a **draft to a reviewer** — it never posts, approves, or reverses an entry.

## 10. Disable / roll back
- Pause: open the deployment → **Status = Not Scheduled** → Save.
- Remove: delete the deployment, the script record, then the files (or `suitecloud object:delete`).
